"""End-to-end game bootstrap and navigation engine for Artale.

Automates the complete workflow from cold emulator / home screen to the
Artale Free Market (自由市場) using a reactive screen state machine:
1. Active Screen State Classification (12 discrete verified visual states)
2. Home screen popup / ad suppression (ESC / KEYCODE_BACK)
3. Dynamic OCR selection of 'Artale (繁體中文版)' (excluding 'Lounge')
4. Closed-loop state progression until Free Market template match
"""

from enum import Enum
import logging
from pathlib import Path
import time
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image
import winocr

from config.coordinates import (
    POS_DISMISS_DRAWER,
    POS_EXIT_MODAL_CANCEL,
    POS_FREE_MARKET_MENU_BUTTON,
    POS_HOME_MSW_ICON,
    POS_LOGIN_BUTTON,
    POS_MENU_BUTTON,
    POS_MSW_PLAY_BUTTON,
    POS_MSW_SEARCH_BUTTON,
    POS_MSW_SEARCH_INPUT,
    POS_SELECT_CHARACTER_BUTTON,
)
from config.settings import ASSETS_DIR, DEVICE_INSTANCE_MAP
from driver.adb_driver import AdbDriver
from driver.emulator_controller import EmulatorController

_logger = logging.getLogger(__name__)

MSW_PACKAGE_NAME = "com.nexon.maplestoryworlds"

# Progressive screencap backoff schedule: 2 + 4 + 6 + 8 = 20 seconds total grace period
SCREENCAP_BACKOFF_SECONDS = (2.0, 4.0, 6.0, 8.0)
MAX_CONSECUTIVE_UNKNOWNS = 20


class ScreenState(Enum):
    """Discrete observable screen states during the Artale bootstrap workflow."""
    UNKNOWN = "UNKNOWN"
    STATE_HOME = "STATE_HOME"
    STATE_MSW_LOADING = "STATE_MSW_LOADING"
    STATE_MSW_LOBBY = "STATE_MSW_LOBBY"
    STATE_MSW_SEARCH = "STATE_MSW_SEARCH"
    STATE_SEARCH_RESULTS = "STATE_SEARCH_RESULTS"
    STATE_ARTALE_DETAILS = "STATE_ARTALE_DETAILS"
    STATE_GAME_CONNECTING = "STATE_GAME_CONNECTING"
    STATE_LOGIN_SCREEN = "STATE_LOGIN_SCREEN"
    STATE_CHAR_SELECT = "STATE_CHAR_SELECT"
    STATE_IN_GAME_WORLD = "STATE_IN_GAME_WORLD"
    STATE_MOBILE_MENU = "STATE_MOBILE_MENU"
    STATE_EXIT_MODAL = "STATE_EXIT_MODAL"
    STATE_FREE_MARKET = "STATE_FREE_MARKET"


def detect_screen_state(frame: Optional[Image.Image]) -> ScreenState:
    """Classifies the captured frame into one of the 12 discrete ScreenStates.

    Args:
        frame: PIL Image captured from the device.

    Returns:
        Identified ScreenState enum.
    """
    if frame is None:
        return ScreenState.UNKNOWN

    frame_rgb = frame.convert("RGB")
    w, h = frame_rgb.size
    arr = np.array(frame_rgb)

    if w == 1280 and h == 720:
        # 0. Exit modal check ("前往大廳" dark dialog with yellow [是] button)
        exit_btn = arr[450:530, 650:945]
        yellow_exit = (
            (exit_btn[:, :, 0] > 240)
            & (exit_btn[:, :, 1] > 160)
            & (exit_btn[:, :, 2] < 60)
        ).sum()
        dialog_bg = arr[220:420, 450:800].mean()
        if yellow_exit > 2000 and dialog_bg < 70:
            return ScreenState.STATE_EXIT_MODAL


        # 1. Free Market check (Template match on minimap header)
        indicator_path = ASSETS_DIR / "free_market_indicator.png"
        if indicator_path.exists():
            tmpl = cv2.imread(str(indicator_path))
            if tmpl is not None:
                roi = cv2.cvtColor(np.array(frame_rgb.crop((0, 0, 200, 150))), cv2.COLOR_RGB2BGR)
                res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
                if cv2.minMaxLoc(res)[1] >= 0.85:
                    return ScreenState.STATE_FREE_MARKET

        # 2. Connecting / loading screen: dark background (>40% pixels < 5)
        if (arr < 5).mean() > 0.40:
            return ScreenState.STATE_GAME_CONNECTING

        # 3. Mobile Menu open: Free Market button in drawer (white_px > 150 and dark bg mean < 60)
        fm_box = arr[410:485, 1100:1180]
        if (fm_box > 220).all(axis=2).sum() > 150 and fm_box.mean() < 60:
            return ScreenState.STATE_MOBILE_MENU

        # 4. In-game world: MENU button (1120..1220, 80..155)
        menu_btn = arr[80:155, 1120:1220]
        if (menu_btn > 220).all(axis=2).sum() > 80:
            return ScreenState.STATE_IN_GAME_WORLD

        # 5. Character select: 選擇角色 wooden board (y: 235..315, x: 760..935)
        char_board = arr[235:315, 760:935]
        dark_text = (char_board < 60).all(axis=2).sum()
        wood = (
            (char_board[:, :, 0] > 100)
            & (char_board[:, :, 1] > 30)
            & (char_board[:, :, 1] < 120)
            & (char_board[:, :, 2] < 50)
        ).sum()
        if dark_text > 30 and wood > 1000:
            return ScreenState.STATE_CHAR_SELECT

        # 6. Login screen: 登入 button (y: 440..505, x: 940..1020)
        login_btn = arr[440:505, 940:1020]
        login_wood = (
            (login_btn[:, :, 0] > 100)
            & (login_btn[:, :, 1] > 40)
            & (login_btn[:, :, 1] < 110)
            & (login_btn[:, :, 2] < 60)
        ).sum()
        if login_wood > 500:
            return ScreenState.STATE_LOGIN_SCREEN

        # 7. Android Home
        return ScreenState.STATE_HOME

    elif w == 720 and h == 1280:
        # Details page: Yellow play button (y: 1090..1190, x: 260..690)
        yellow_btn = arr[1090:1190, 260:690]
        yellow_px = (
            (yellow_btn[:, :, 0] > 220)
            & (yellow_btn[:, :, 1] > 150)
            & (yellow_btn[:, :, 1] < 210)
            & (yellow_btn[:, :, 2] < 70)
        ).sum()
        if yellow_px > 2000:
            return ScreenState.STATE_ARTALE_DETAILS

        # Search results vs search input: check std of middle section
        tab_crop = arr[130:170, 50:170]
        dark_tab = (tab_crop < 60).all(axis=2).sum()
        if dark_tab > 100 and arr[30:90].mean() > 200:
            if arr[250:600].std() > 25.0:
                return ScreenState.STATE_SEARCH_RESULTS
            return ScreenState.STATE_MSW_SEARCH

        # MSW Lobby: top bar magnifier (y: 40..90, x: 380..440)
        mag_crop = arr[40:90, 380:440]
        dark_mag = (mag_crop < 100).all(axis=2).sum()
        if dark_mag > 100 and arr[30:90].mean() > 200:
            return ScreenState.STATE_MSW_LOBBY

        # MSW Splash / loading
        cyan_px = (
            (arr[:, :, 0] < 150) & (arr[:, :, 1] > 180) & (arr[:, :, 2] > 200)
        ).sum()
        if cyan_px > 10000:
            return ScreenState.STATE_MSW_LOADING

    return ScreenState.UNKNOWN


def find_artale_card_coordinates(frame: Image.Image) -> Optional[Tuple[int, int]]:
    """Dynamically locates the Artale (繁體中文版) card using winocr."""
    try:
        res = winocr.recognize_pil_sync(frame, lang="zh-Hant-TW")
    except Exception as err:
        _logger.error(f"OCR failed while detecting Artale card: {err}")
        return None

    candidates = []
    for line in res.get("lines", []):
        text = line.get("text", "")
        if "Lounge" in text or "lounge" in text:
            continue

        if any(kw in text for kw in ["繁體", "中文版", "繁 體", "Artale"]):
            for w in line.get("words", []):
                rect = w.get("bounding_rect", {})
                if rect and 350 <= rect.get("y", 0) <= 650:
                    candidates.append((w.get("text", ""), rect))

    if not candidates:
        _logger.warning("No candidate tokens found for Artale (繁體中文版).")
        return None

    preferred = [
        c for c in candidates if any(k in c[0] for k in ["繁", "體", "中", "文", "版"])
    ]
    chosen = preferred[0] if preferred else candidates[0]
    rect = chosen[1]

    card_tap_x = int(rect["x"] + rect["width"] / 2)
    card_tap_y = int(rect["y"] - 120)

    _logger.debug(
        f"Detected Artale card token '{chosen[0]}' at ({rect['x']:.0f}, {rect['y']:.0f}). Target: ({card_tap_x}, {card_tap_y})"
    )
    return card_tap_x, card_tap_y


class GameBootstrapper:
    """Manages full lifecycle bootstrapping from emulator home to Free Market."""

    def __init__(
        self,
        adb: AdbDriver,
        controller: Optional[EmulatorController] = None,
        instance_name: Optional[str] = None,
    ) -> None:
        """Initializes GameBootstrapper with ADB driver and optional controller.

        Args:
            adb: Active AdbDriver instance for screen capture and touch input.
            controller: Optional EmulatorController instance. Defaults to a new instance.
            instance_name: Optional LDPlayer instance name (e.g. '槍手'). If omitted,
                automatically resolved from adb.device_id.
        """
        self.adb = adb
        self.controller = controller or EmulatorController()
        self.instance_name = instance_name or DEVICE_INSTANCE_MAP.get(adb.device_id)

    def restart_instance_clean(self) -> bool:
        """Kills and relaunches the LDPlayer instance to ensure fresh state.

        Returns:
            bool: True if instance was successfully restarted and ready, False otherwise.
        """
        dev = self.adb.device_id
        if not self.instance_name:
            _logger.debug(f"[{dev}] No instance_name specified. Falling back to return_home_and_cleanup.")
            self.return_home_and_cleanup()
            return True

        _logger.info(f"Killing LDPlayer instance '{self.instance_name}' ({dev})...")
        self.controller.quit_instance(self.instance_name)
        time.sleep(2.0)
        self.controller.force_kill_instance(self.instance_name)
        time.sleep(2.0)

        _logger.info(f"Relaunching clean LDPlayer instance '{self.instance_name}'...")
        if not self.controller.launch_instance(self.instance_name, max_wait_sec=60):
            _logger.error(f"Failed to relaunch instance '{self.instance_name}'.")
            return False

        time.sleep(5.0)
        _logger.debug(f"[{dev}] Sending ESC / BACK events to dismiss home popups...")
        self.adb.send_esc(count=4, delay_sec=0.5)
        time.sleep(1.0)
        return True

    def return_home_and_cleanup(self) -> None:
        """Closes running apps, returns to Android home screen, and dismisses popups."""
        dev = self.adb.device_id
        _logger.debug(f"[{dev}] Closing opening apps and returning to home...")
        self.adb._run_adb("shell", "am", "force-stop", MSW_PACKAGE_NAME)
        time.sleep(0.5)
        self.adb.keyevent(3)  # KEYCODE_HOME
        time.sleep(1.0)
        _logger.debug(f"[{dev}] Sending ESC / BACK events to dismiss home popups...")
        self.adb.send_esc(count=4, delay_sec=0.4)
        time.sleep(0.8)

    def bootstrap_to_free_market(
        self, clean_reboot: bool = False, max_timeout_sec: int = 180
    ) -> bool:
        """Executes reactive closed-loop bootstrap until Free Market is reached.

        Checks the actual screen state before every action and transitions
        reactively.

        Args:
            clean_reboot: Whether to force-kill and restart the emulator before bootstrapping.
            max_timeout_sec: Maximum seconds allowed to reach Free Market before aborting.

        Returns:
            bool: True if successfully confirmed in Free Market, False if timed out.
        """
        dev = self.adb.device_id
        _logger.debug(f"[{dev}] Starting reactive closed-loop bootstrap to Free Market...")

        # 1. Clean reboot if requested
        if clean_reboot and self.instance_name:
            if not self.restart_instance_clean():
                return False
        else:
            if self.instance_name and not self.controller.is_running(self.instance_name):
                _logger.info(f"Instance '{self.instance_name}' not running. Booting...")
                if not self.controller.launch_instance(self.instance_name):
                    return False

        if self.adb.is_free_market():
            _logger.debug(f"[{dev}] Already confirmed in Free Market.")
            return True

        start_t = time.time()
        consecutive_unknowns = 0
        consecutive_screencap_fails = 0

        while time.time() - start_t < max_timeout_sec:
            frame = self.adb.screencap()
            state = detect_screen_state(frame)
            _logger.debug(f"[{dev}] Observed screen state: {state.value}")

            if state != ScreenState.UNKNOWN:
                consecutive_unknowns = 0
                consecutive_screencap_fails = 0

            if state == ScreenState.STATE_EXIT_MODAL:
                _logger.debug(f"[{dev}] Detected exit confirmation modal. Clicking [否] to dismiss...")
                self.adb.tap(POS_EXIT_MODAL_CANCEL.x, POS_EXIT_MODAL_CANCEL.y)
                time.sleep(1.5)

            elif state == ScreenState.STATE_FREE_MARKET:
                # If mobile menu drawer is still open, dismiss it cleanly by tapping outside
                arr = np.array(frame.convert("RGB"))
                fm_box = arr[410:485, 1100:1180]
                if (fm_box > 220).all(axis=2).sum() > 150 and fm_box.mean() < 60:
                    _logger.debug(f"[{dev}] Closing open menu drawer in Free Market by tapping outside...")
                    self.adb.tap(POS_DISMISS_DRAWER.x, POS_DISMISS_DRAWER.y)
                    time.sleep(1.0)
                _logger.info(f"[{dev}] Reached Free Market.")
                return True

            elif state == ScreenState.STATE_HOME:
                _logger.debug(f"[{dev}] Clearing home popups with ESC and launching MSW...")
                self.adb.send_esc(count=2, delay_sec=0.3)
                time.sleep(0.5)
                self.adb.tap(POS_HOME_MSW_ICON.x, POS_HOME_MSW_ICON.y)
                time.sleep(3.0)

            elif state == ScreenState.STATE_MSW_LOADING:
                _logger.debug(f"[{dev}] MapleStory Worlds loading splash. Waiting...")
                time.sleep(3.0)

            elif state == ScreenState.STATE_MSW_LOBBY:
                _logger.debug(f"[{dev}] In MSW lobby. Clicking search icon...")
                self.adb.tap(POS_MSW_SEARCH_BUTTON.x, POS_MSW_SEARCH_BUTTON.y)
                time.sleep(2.5)

            elif state == ScreenState.STATE_MSW_SEARCH:
                _logger.debug(f"[{dev}] In search view. Focusing input and searching 'Artale'...")
                self.adb.tap(POS_MSW_SEARCH_INPUT.x, POS_MSW_SEARCH_INPUT.y)
                time.sleep(0.8)
                self.adb._run_adb("shell", "input", "text", "Artale")
                time.sleep(0.5)
                self.adb.press_enter()
                time.sleep(3.0)

            elif state == ScreenState.STATE_SEARCH_RESULTS:
                _logger.debug(f"[{dev}] In search results. Dynamically identifying Artale card...")
                coords = find_artale_card_coordinates(frame)
                if coords:
                    self.adb.tap(coords[0], coords[1])
                    time.sleep(3.5)
                else:
                    _logger.warning(f"[{dev}] Could not locate card via OCR. Retrying in 2s...")
                    time.sleep(2.0)

            elif state == ScreenState.STATE_ARTALE_DETAILS:
                _logger.debug(f"[{dev}] On Artale details page. Clicking [▶ 遊玩]...")
                self.adb.tap(POS_MSW_PLAY_BUTTON.x, POS_MSW_PLAY_BUTTON.y)
                time.sleep(5.0)

            elif state == ScreenState.STATE_GAME_CONNECTING:
                _logger.debug(f"[{dev}] Artale connecting / loading assets. Waiting...")
                time.sleep(3.5)

            elif state == ScreenState.STATE_LOGIN_SCREEN:
                _logger.debug(f"[{dev}] On title login screen. Clicking [登入]...")
                self.adb.tap(POS_LOGIN_BUTTON.x, POS_LOGIN_BUTTON.y)
                time.sleep(4.5)

            elif state == ScreenState.STATE_CHAR_SELECT:
                _logger.debug(
                    f"[{dev}] On character select screen. Clicking [選擇角色] at ({POS_SELECT_CHARACTER_BUTTON.x}, {POS_SELECT_CHARACTER_BUTTON.y})..."
                )
                self.adb.touch(
                    POS_SELECT_CHARACTER_BUTTON.x,
                    POS_SELECT_CHARACTER_BUTTON.y,
                    duration_ms=150,
                )
                time.sleep(4.0)

            elif state == ScreenState.STATE_IN_GAME_WORLD:
                _logger.debug(f"[{dev}] In-game world HUD active. Clicking [::: MENU]...")
                self.adb.tap(POS_MENU_BUTTON.x, POS_MENU_BUTTON.y)
                time.sleep(2.0)

            elif state == ScreenState.STATE_MOBILE_MENU:
                _logger.debug(f"[{dev}] Mobile menu drawer open. Clicking [自由市場]...")
                self.adb.tap(
                    POS_FREE_MARKET_MENU_BUTTON.x, POS_FREE_MARKET_MENU_BUTTON.y
                )
                time.sleep(5.0)

            else:  # UNKNOWN
                consecutive_unknowns += 1
                if frame is None:
                    consecutive_screencap_fails += 1
                    backoff_idx = consecutive_screencap_fails - 1
                    if backoff_idx < len(SCREENCAP_BACKOFF_SECONDS):
                        wait_sec = SCREENCAP_BACKOFF_SECONDS[backoff_idx]
                        _logger.warning(
                            f"[{dev}] Screen capture failed (attempt {consecutive_screencap_fails}/{len(SCREENCAP_BACKOFF_SECONDS)}). Backing off {int(wait_sec)}s..."
                        )
                        if consecutive_screencap_fails == 2:
                            self.adb.reconnect()
                        time.sleep(wait_sec)
                        continue
                    else:
                        _logger.error(
                            f"[{dev}] Freeze confirmed after {int(sum(SCREENCAP_BACKOFF_SECONDS))}s backoff (screencap failed {consecutive_screencap_fails} times). Respawning instance '{self.instance_name}'..."
                        )
                        if self.restart_instance_clean():
                            consecutive_unknowns = 0
                            consecutive_screencap_fails = 0
                            time.sleep(5.0)
                            continue
                        else:
                            _logger.error(f"[{dev}] Emergency restart failed.")
                            return False
                else:
                    consecutive_screencap_fails = 0
                    _logger.warning(
                        f"[{dev}] Unknown screen state (count={consecutive_unknowns}/{MAX_CONSECUTIVE_UNKNOWNS}). Retrying capture..."
                    )
                    if consecutive_unknowns >= MAX_CONSECUTIVE_UNKNOWNS:
                        _logger.error(
                            f"[{dev}] Freeze detected. In unknown state for {consecutive_unknowns} consecutive cycles. Respawning instance '{self.instance_name}'..."
                        )
                        if self.restart_instance_clean():
                            consecutive_unknowns = 0
                            consecutive_screencap_fails = 0
                            time.sleep(5.0)
                            continue
                        else:
                            _logger.error(f"[{dev}] Emergency restart failed.")
                            return False

                    if consecutive_unknowns == 4:
                        _logger.warning(f"[{dev}] Stuck in unknown state. Sending ESC to dismiss popup...")
                        self.adb.send_esc(count=2, delay_sec=0.5)
                    time.sleep(2.0)

        _logger.error(f"[{dev}] Timed out after {max_timeout_sec}s without reaching Free Market.")
        return False


if __name__ == "__main__":
    import argparse
    from config.settings import setup_logging

    setup_logging(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Bootstrap emulator to Artale Free Market.")
    parser.add_argument("--device", type=str, default="emulator-5560", help="ADB device ID")
    parser.add_argument("--instance", type=str, default=None, help="LDPlayer instance name")
    parser.add_argument("--reboot", action="store_true", help="Kill and cleanly restart instance before bootstrap")
    args = parser.parse_args()

    driver = AdbDriver(device_id=args.device)
    bootstrapper = GameBootstrapper(driver, instance_name=args.instance)
    success = bootstrapper.bootstrap_to_free_market(clean_reboot=args.reboot)
    print(f"Bootstrap finished: {'SUCCESS' if success else 'FAILED'}")
