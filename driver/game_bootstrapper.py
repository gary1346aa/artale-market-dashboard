"""End-to-end game bootstrap and navigation engine for Artale.

Automates the complete workflow from cold emulator / home screen to the
Artale Free Market (自由市場) using a reactive screen state machine:
1. Active Screen State Classification (12 discrete verified visual states)
2. Home screen popup / ad suppression (ESC / KEYCODE_BACK)
3. Dynamic OCR selection of 'Artale (繁體中文版)' (excluding 'Lounge')
4. Closed-loop state progression until Free Market template match (100%)
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
from config.settings import ASSETS_DIR
from driver.adb_driver import AdbDriver
from driver.emulator_controller import EmulatorController

_logger = logging.getLogger(__name__)

MSW_PACKAGE_NAME = "com.nexon.maplestoryworlds"


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

        # 2. Connecting / loading screen: majority pure pitch black (>40% pixels < 5)
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
        _logger.error("OCR failed while detecting Artale card: %s", err)
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

    _logger.info(
        "Detected Artale card token '%s' at (%.0f, %.0f). Target: (%d, %d)",
        chosen[0],
        rect["x"],
        rect["y"],
        card_tap_x,
        card_tap_y,
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
        """Initializes GameBootstrapper with ADB driver and optional controller."""
        self.adb = adb
        self.controller = controller or EmulatorController()
        if not instance_name:
            dev_map = {
                "emulator-5560": "槍手",
                "emulator-5562": "打火機",
                "emulator-5568": "弩手",
            }
            self.instance_name = dev_map.get(adb.device_id, instance_name)
        else:
            self.instance_name = instance_name


    def restart_instance_clean(self) -> bool:
        """Kills and relaunches the LDPlayer instance to guarantee a 100% clean baseline."""
        dev = self.adb.device_id
        if not self.instance_name:
            _logger.info("[%s] No instance_name specified. Falling back to return_home_and_cleanup.", dev)
            self.return_home_and_cleanup()
            return True

        _logger.info("Killing LDPlayer instance '%s' (%s)...", self.instance_name, dev)
        self.controller.quit_instance(self.instance_name)
        time.sleep(2.0)
        self.controller.force_kill_instance(self.instance_name)
        time.sleep(2.0)

        _logger.info("Relaunching clean LDPlayer instance '%s'...", self.instance_name)
        if not self.controller.launch_instance(self.instance_name, max_wait_sec=60):
            _logger.error("Failed to relaunch instance '%s'.", self.instance_name)
            return False

        time.sleep(5.0)
        _logger.info("[%s] Sending ESC / BACK events to dismiss home popups...", dev)
        self.adb.send_esc(count=4, delay_sec=0.5)
        time.sleep(1.0)
        return True

    def return_home_and_cleanup(self) -> None:
        """Closes opening apps, returns to Android home screen, and dismisses popups."""
        dev = self.adb.device_id
        _logger.info("[%s] Closing opening apps and returning to home...", dev)
        self.adb._run_adb("shell", "am", "force-stop", MSW_PACKAGE_NAME)
        time.sleep(0.5)
        self.adb.keyevent(3)  # KEYCODE_HOME
        time.sleep(1.0)
        _logger.info("[%s] Sending ESC / BACK events to dismiss home popups...", dev)
        self.adb.send_esc(count=4, delay_sec=0.4)
        time.sleep(0.8)

    def bootstrap_to_free_market(
        self, clean_reboot: bool = False, max_timeout_sec: int = 180
    ) -> bool:
        """Executes reactive closed-loop bootstrap until Free Market is reached.

        Checks the actual screen state before every action and transitions
        reactively.
        """
        dev = self.adb.device_id
        _logger.info("[%s] Starting reactive closed-loop bootstrap to Free Market...", dev)

        # 1. Clean reboot if requested
        if clean_reboot and self.instance_name:
            if not self.restart_instance_clean():
                return False
        else:
            if self.instance_name and not self.controller.is_running(self.instance_name):
                _logger.info("Instance '%s' not running. Booting...", self.instance_name)
                if not self.controller.launch_instance(self.instance_name):
                    return False

        if self.adb.is_free_market():
            _logger.info("[%s] Already confirmed in Free Market.", dev)
            return True

        start_t = time.time()
        consecutive_unknowns = 0
        consecutive_screencap_fails = 0

        while time.time() - start_t < max_timeout_sec:
            frame = self.adb.screencap()
            state = detect_screen_state(frame)
            _logger.info("[%s] Observed screen state: %s", dev, state.value)

            if state != ScreenState.UNKNOWN:
                consecutive_unknowns = 0
                consecutive_screencap_fails = 0

            if state == ScreenState.STATE_EXIT_MODAL:
                _logger.info("[%s] Detected exit confirmation modal. Clicking [否] to dismiss...", dev)
                self.adb.tap(POS_EXIT_MODAL_CANCEL.x, POS_EXIT_MODAL_CANCEL.y)
                time.sleep(1.5)

            elif state == ScreenState.STATE_FREE_MARKET:
                # If mobile menu drawer is still open, dismiss it cleanly by tapping outside
                arr = np.array(frame.convert("RGB"))
                fm_box = arr[410:485, 1100:1180]
                if (fm_box > 220).all(axis=2).sum() > 150 and fm_box.mean() < 60:
                    _logger.info("[%s] Closing open menu drawer in Free Market by tapping outside...", dev)
                    self.adb.tap(POS_DISMISS_DRAWER.x, POS_DISMISS_DRAWER.y)
                    time.sleep(1.0)
                _logger.info("[%s] Successfully reached Free Market!", dev)
                return True

            elif state == ScreenState.STATE_HOME:
                _logger.info("[%s] Clearing home popups with ESC and launching MSW...", dev)
                self.adb.send_esc(count=2, delay_sec=0.3)
                time.sleep(0.5)
                self.adb.tap(POS_HOME_MSW_ICON.x, POS_HOME_MSW_ICON.y)
                time.sleep(3.0)

            elif state == ScreenState.STATE_MSW_LOADING:
                _logger.info("[%s] MapleStory Worlds loading splash. Waiting...", dev)
                time.sleep(3.0)

            elif state == ScreenState.STATE_MSW_LOBBY:
                _logger.info("[%s] In MSW lobby. Clicking search icon...", dev)
                self.adb.tap(POS_MSW_SEARCH_BUTTON.x, POS_MSW_SEARCH_BUTTON.y)
                time.sleep(2.5)

            elif state == ScreenState.STATE_MSW_SEARCH:
                _logger.info("[%s] In search view. Focusing input and searching 'Artale'...", dev)
                self.adb.tap(POS_MSW_SEARCH_INPUT.x, POS_MSW_SEARCH_INPUT.y)
                time.sleep(0.8)
                self.adb._run_adb("shell", "input", "text", "Artale")
                time.sleep(0.5)
                self.adb.press_enter()
                time.sleep(3.0)

            elif state == ScreenState.STATE_SEARCH_RESULTS:
                _logger.info("[%s] In search results. Dynamically identifying Artale card...", dev)
                coords = find_artale_card_coordinates(frame)
                if coords:
                    self.adb.tap(coords[0], coords[1])
                    time.sleep(3.5)
                else:
                    _logger.warning("[%s] Could not locate card via OCR. Retrying in 2s...", dev)
                    time.sleep(2.0)

            elif state == ScreenState.STATE_ARTALE_DETAILS:
                _logger.info("[%s] On Artale details page. Clicking [▶ 遊玩]...", dev)
                self.adb.tap(POS_MSW_PLAY_BUTTON.x, POS_MSW_PLAY_BUTTON.y)
                time.sleep(5.0)

            elif state == ScreenState.STATE_GAME_CONNECTING:
                _logger.info("[%s] Artale connecting / loading assets. Waiting...", dev)
                time.sleep(3.5)

            elif state == ScreenState.STATE_LOGIN_SCREEN:
                _logger.info("[%s] On title login screen. Clicking [登入]...", dev)
                self.adb.tap(POS_LOGIN_BUTTON.x, POS_LOGIN_BUTTON.y)
                time.sleep(4.5)

            elif state == ScreenState.STATE_CHAR_SELECT:
                _logger.info(
                    "[%s] On character select screen. Clicking [選擇角色] at (%d, %d)...",
                    dev,
                    POS_SELECT_CHARACTER_BUTTON.x,
                    POS_SELECT_CHARACTER_BUTTON.y,
                )
                self.adb.touch(
                    POS_SELECT_CHARACTER_BUTTON.x,
                    POS_SELECT_CHARACTER_BUTTON.y,
                    duration_ms=150,
                )
                time.sleep(4.0)

            elif state == ScreenState.STATE_IN_GAME_WORLD:
                _logger.info("[%s] In-game world HUD active. Clicking [::: MENU]...", dev)
                self.adb.tap(POS_MENU_BUTTON.x, POS_MENU_BUTTON.y)
                time.sleep(2.0)

            elif state == ScreenState.STATE_MOBILE_MENU:
                _logger.info("[%s] Mobile menu drawer open. Clicking [自由市場]...", dev)
                self.adb.tap(
                    POS_FREE_MARKET_MENU_BUTTON.x, POS_FREE_MARKET_MENU_BUTTON.y
                )
                time.sleep(5.0)

            else:  # UNKNOWN
                consecutive_unknowns += 1
                if frame is None:
                    consecutive_screencap_fails += 1
                    time.sleep(1.5)
                else:
                    consecutive_screencap_fails = 0

                _logger.warning(
                    "[%s] Unrecognized screen state (count=%d, screencap_fails=%d). Retrying capture...",
                    dev,
                    consecutive_unknowns,
                    consecutive_screencap_fails,
                )

                # Freeze Detection Watchdog: allow up to 10 screencap fails during cold OS initialization
                if consecutive_screencap_fails >= 10 or consecutive_unknowns >= 15:
                    _logger.error(
                        "[%s] FREEZE / CRASH DETECTED! Screen capture or OS is unresponsive. Auto-killing and respawning instance '%s'...",
                        dev,
                        self.instance_name,
                    )
                    if self.restart_instance_clean():
                        consecutive_unknowns = 0
                        consecutive_screencap_fails = 0
                        time.sleep(5.0)
                        continue
                    else:
                        _logger.error("[%s] Emergency restart failed!", dev)
                        return False

                if consecutive_unknowns == 4:
                    _logger.warning("[%s] Stuck in unknown state. Sending ESC to dismiss any popup...", dev)
                    self.adb.send_esc(count=2, delay_sec=0.5)
                time.sleep(2.0)


        _logger.error("[%s] Timed out after %ds without reaching Free Market.", dev, max_timeout_sec)
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
