"""High-performance Android Debug Bridge (ADB) driver for game automation.

Enables zero-focus, zero-mouse-interference game automation with direct
SurfaceFlinger memory frame dumps, fast input injection, and ADBKeyBoard IME.
"""

import base64
import io
import json
import logging
from pathlib import Path
import subprocess
import time
from typing import Dict, List, Optional, Tuple, Union

from PIL import Image

from config.coordinates import (
    POS_AUCTION_BUTTON,
    POS_CONFIRM_EXIT,
    POS_LEAVE_AUCTION,
    POS_MENU_BUTTON,
    POS_STOP_DIALOG,
)
from config.settings import AUCTION_COOLDOWN_FILE, DEFAULT_ADB

_logger = logging.getLogger(__name__)

_GLOBAL_AUCTION_EXIT_TIMES: Dict[str, float] = {}


def _load_cooldowns() -> Dict[str, float]:
    """Loads auction exit cooldowns from disk."""
    try:
        if AUCTION_COOLDOWN_FILE.exists():
            with open(AUCTION_COOLDOWN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as err:
        _logger.debug("Could not read cooldown file: %s", err)
    return {}


def _save_cooldown(device_id: str, ts: float) -> None:
    """Persists an auction exit timestamp to disk for a given device."""
    try:
        AUCTION_COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        cds = _load_cooldowns()
        cds[device_id] = ts
        with open(AUCTION_COOLDOWN_FILE, "w", encoding="utf-8") as f:
            json.dump(cds, f, indent=2)
    except Exception as err:
        _logger.debug("Could not save auction cooldown: %s", err)


class AdbDriver:
    """Background ADB driver for LDPlayer instances.

    Attributes:
        device_id: ADB device serial (e.g. 'emulator-5558' or '127.0.0.1:5555').
        adb_path: Path to adb.exe executable.
    """

    def __init__(
        self,
        device_id: str = "emulator-5558",
        adb_path: Union[str, Path] = DEFAULT_ADB,
    ) -> None:
        """Initializes the AdbDriver and ensures ADBKeyBoard is active."""
        self.device_id = device_id
        self.adb_path = str(adb_path)
        self._ensure_adb_keyboard()

    @classmethod
    def list_attached_devices(
        cls, adb_path: Union[str, Path] = DEFAULT_ADB
    ) -> List[str]:
        """Lists all attached and online ADB devices.

        Args:
            adb_path: Path to adb.exe binary.

        Returns:
            List of device serial IDs.
        """
        try:
            p = subprocess.run(
                [str(adb_path), "devices"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            devs: List[str] = []
            for line in p.stdout.splitlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    devs.append(parts[0])
            return devs
        except Exception as err:
            _logger.error("Error listing attached ADB devices: %s", err)
            return []

    def _run_adb(
        self, *args: str, check: bool = False
    ) -> subprocess.CompletedProcess:
        """Executes an ADB command directed to this device."""
        cmd = [self.adb_path, "-s", self.device_id] + list(args)
        return subprocess.run(cmd, capture_output=True, check=check)

    def _ensure_adb_keyboard(self) -> None:
        """Verifies and enables ADBKeyBoard IME on the emulator."""
        try:
            self._run_adb(
                "shell", "ime", "enable", "com.android.adbkeyboard/.AdbIME"
            )
            self._run_adb(
                "shell", "ime", "set", "com.android.adbkeyboard/.AdbIME"
            )
        except Exception as err:
            _logger.warning(
                "Could not auto-enable ADBKeyBoard on %s: %s",
                self.device_id,
                err,
            )

    def screencap(
        self,
        crop: Optional[Tuple[int, int, int, int]] = None,
        as_jpeg: bool = False,
        jpeg_quality: int = 85,
    ) -> Optional[Image.Image]:
        """Captures display buffer via high-performance raw SurfaceFlinger dump.

        Avoids Android-side PNG compression overhead (~3x faster, ~110-125ms).
        If crop is specified, slices the memory buffer directly before PIL instantiation.

        Args:
            crop: Optional (x1, y1, x2, y2) bounding box to crop.
            as_jpeg: Whether to compress into JPEG in-memory.
            jpeg_quality: Quality factor for JPEG compression.

        Returns:
            PIL RGB Image or None on failure.
        """
        try:
            p = subprocess.run(
                [self.adb_path, "-s", self.device_id, "exec-out", "screencap"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2.0,
                check=False,
            )
            if p.returncode == 0 and p.stdout and len(p.stdout) >= 16:
                data = p.stdout
                w = int.from_bytes(data[0:4], "little")
                h = int.from_bytes(data[4:8], "little")
                expected = w * h * 4
                if len(data) >= 16 + expected:
                    if crop:
                        x1 = max(0, min(crop[0], w))
                        y1 = max(0, min(crop[1], h))
                        x2 = max(x1, min(crop[2], w))
                        y2 = max(y1, min(crop[3], h))
                        cw, ch = x2 - x1, y2 - y1
                        stride = w * 4
                        crop_bytes = b"".join(
                            data[
                                16 + y * stride + x1 * 4 : 16 + y * stride + x2 * 4
                            ]
                            for y in range(y1, y2)
                        )
                        img = Image.frombytes(
                            "RGBA", (cw, ch), crop_bytes, "raw", "RGBA"
                        ).convert("RGB")
                    else:
                        img = Image.frombytes(
                            "RGBA", (w, h), data[16 : 16 + expected], "raw", "RGBA"
                        ).convert("RGB")

                    if as_jpeg:
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=jpeg_quality)
                        buf.seek(0)
                        return Image.open(buf)
                    return img
        except Exception as err:
            _logger.debug(
                "ADB raw screencap failed on %s: %s", self.device_id, err
            )

        # Fallback to standard PNG screencap
        try:
            p = subprocess.run(
                [
                    self.adb_path,
                    "-s",
                    self.device_id,
                    "exec-out",
                    "screencap",
                    "-p",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2.0,
                check=False,
            )
            if p.returncode == 0 and p.stdout:
                img = Image.open(io.BytesIO(p.stdout)).convert("RGB")
                if crop:
                    img = img.crop(crop)
                if as_jpeg:
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=jpeg_quality)
                    buf.seek(0)
                    return Image.open(buf)
                return img
        except Exception as err:
            _logger.error(
                "ADB fallback screencap failed on %s: %s", self.device_id, err
            )
        return None

    def tap(self, x: int, y: int) -> None:
        """Taps screen coordinates without moving host mouse cursor."""
        self._run_adb("shell", "input", "tap", str(int(x)), str(int(y)))

    def keyevent(self, code: int) -> None:
        """Sends an Android keycode event (e.g. 111 for ESC, 66 for ENTER)."""
        self._run_adb("shell", "input", "keyevent", str(code))

    def press_esc(self) -> None:
        """Sends ESC keyevent."""
        self.keyevent(111)

    def press_enter(self) -> None:
        """Sends ENTER keyevent."""
        self.keyevent(66)

    def input_chinese(self, text: str) -> None:
        """Injects Unicode / Chinese text into the active field via ADBKeyBoard.

        Args:
            text: UTF-8 string to input.
        """
        clean_text = text.strip()
        self._run_adb("shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT")
        time.sleep(0.05)
        b64 = base64.b64encode(clean_text.encode("utf-8")).decode("ascii")
        self._run_adb(
            "shell",
            "am",
            "broadcast",
            "-a",
            "ADB_INPUT_B64",
            "--es",
            "msg",
            b64,
        )
        time.sleep(0.15)

    def is_lobby_dialog_open(
        self, frame: Optional[Image.Image] = None
    ) -> bool:
        """Checks if '前往大廳 是否結束遊玩並前往大廳？' exit dialog is open."""
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False
        try:
            p_yes = frame.getpixel((741, 490))[:3]
            is_orange = (
                p_yes[0] > 220 and 140 < p_yes[1] < 210 and p_yes[2] < 80
            )
            p_no = frame.getpixel((481, 490))[:3]
            is_gray = (
                (p_no[0] > 180 and p_no[1] > 180 and p_no[2] > 180)
                or (
                    abs(p_no[0] - p_no[1]) < 10
                    and abs(p_no[1] - p_no[2]) < 10
                    and 40 < p_no[0] < 160
                )
            )
            return is_orange and is_gray
        except Exception:
            return False

    def is_error_modal_open(
        self, frame: Optional[Image.Image] = None
    ) -> bool:
        """Checks if '沒有查詢的道具。' or warning modal is open."""
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False
        try:
            p_tri = frame.getpixel((635, 365))[:3]
            has_tri = p_tri[0] > 220 and p_tri[1] > 170 and p_tri[2] < 50
            p_cyan = frame.getpixel((640, 420))[:3]
            has_cyan = p_cyan[1] > 110 and p_cyan[2] > 120 and p_cyan[0] < 60
            return has_tri and has_cyan
        except Exception:
            return False

    def is_exit_cooldown_dialog_open(
        self, frame: Optional[Image.Image] = None
    ) -> bool:
        """Checks if '退出後需等待一段時間才能再進入...' notice is open."""
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False
        try:
            p_btn = frame.getpixel((815, 450))[:3]
            btn_ok = (
                70 <= p_btn[0] <= 130
                and 30 <= p_btn[1] <= 80
                and p_btn[2] <= 50
            )
            p_bg = frame.getpixel((600, 300))[:3]
            bg_ok = (
                20 <= p_bg[0] <= 65
                and 40 <= p_bg[1] <= 95
                and 60 <= p_bg[2] <= 130
            )
            return btn_ok and bg_ok
        except Exception:
            return False

    def is_npc_dialog_open(
        self, frame: Optional[Image.Image] = None
    ) -> bool:
        """Checks if an NPC dialog with [停止對話] is open in Free Market."""
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False
        try:
            p_btn = frame.getpixel((349, 461))[:3]
            btn_ok = (
                p_btn[1] > 160
                and p_btn[1] >= p_btn[0]
                and p_btn[1] > p_btn[2] + 40
            )
            p_bg = frame.getpixel((500, 300))[:3]
            bg_ok = p_bg[0] > 220 and p_bg[1] > 220 and p_bg[2] > 220
            return btn_ok and bg_ok
        except Exception:
            return False

    def handle_lingering_popups(
        self, frame: Optional[Image.Image] = None
    ) -> bool:
        """Detects and dismisses lingering popups or dialogue blocking UI.

        Returns:
            True if any modal was dismissed, False otherwise.
        """
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False

        if self.is_lobby_dialog_open(frame):
            _logger.info(
                "[%s] Dismissing '前往大廳' prompt by tapping [ 否 ]...",
                self.device_id,
            )
            self.tap(481, 490)
            time.sleep(0.4)
            return True

        if self.is_exit_cooldown_dialog_open(frame):
            _logger.info(
                "[%s] Dismissing auction exit cooldown notice...",
                self.device_id,
            )
            self.tap(*POS_CONFIRM_EXIT)
            time.sleep(0.4)
            return True

        if self.is_npc_dialog_open(frame):
            _logger.info(
                "[%s] Dismissing Free Market NPC dialogue...",
                self.device_id,
            )
            self.tap(*POS_STOP_DIALOG)
            time.sleep(0.4)
            return True

        if self.is_error_modal_open(frame):
            _logger.info(
                "[%s] Dismissing warning modal via neutral tap...",
                self.device_id,
            )
            self.tap(640, 420)
            time.sleep(0.4)
            return True

        return False

    def is_auction_open(self, frame: Optional[Image.Image] = None) -> bool:
        """Verifies if the Auction House modal is currently open.

        Args:
            frame: Optional pre-captured PIL Image.

        Returns:
            True if at least 2 key invariant landmarks match.
        """
        if frame is None:
            frame = self.screencap()
        if not frame or frame.width < 1000 or frame.height < 600:
            return False

        if self.handle_lingering_popups(frame):
            frame = self.screencap()
            if not frame:
                return False

        try:
            # 1. Minimap check: Minimap at (30, 18) is covered when AH is open
            p_mm = frame.getpixel((30, 18))[:3]
            if p_mm[0] > 200 and p_mm[1] > 200 and p_mm[2] > 200:
                return False

            # 2. Sidebar green '開始搜尋' button: x in 280..340, y in 535..558
            green_count = sum(
                1
                for x in range(280, 340, 5)
                for y in range(535, 558, 3)
                if frame.getpixel((x, y))[1] > 130
                and frame.getpixel((x, y))[0] > 100
                and frame.getpixel((x, y))[2] < 70
                and frame.getpixel((x, y))[1] > frame.getpixel((x, y))[0] + 15
            )
            green_ok = green_count >= 5

            # 3. Top-right '離開' button dark container with white text
            p_leave_bg = frame.getpixel((975, 40))[:3]
            bg_ok = (
                20 <= p_leave_bg[0] <= 55
                and 20 <= p_leave_bg[1] <= 55
                and 20 <= p_leave_bg[2] <= 55
            )
            text_count = sum(
                1
                for x in range(990, 1040, 3)
                for y in range(32, 48, 2)
                if all(c > 170 for c in frame.getpixel((x, y))[:3])
            )
            leave_ok = bg_ok and text_count >= 4

            # 4. Auction house header tab area (100, 120) dark frame
            p_hdr = frame.getpixel((100, 120))[:3]
            hdr_ok = p_hdr[0] < 70 and p_hdr[1] < 70 and p_hdr[2] < 70

            return sum((green_ok, leave_ok, hdr_ok)) >= 2
        except Exception as err:
            _logger.debug("Error checking is_auction_open: %s", err)
            return False

    def is_free_market(self, frame: Optional[Image.Image] = None) -> bool:
        """Verifies if the character is standing in the Free Market map."""
        if frame is None:
            frame = self.screencap()
        if not frame or frame.width < 1000 or frame.height < 600:
            return False
        try:
            p_hp = frame.getpixel((600, 647))[:3]
            p_mp = frame.getpixel((600, 668))[:3]
            hp_ok = p_hp[0] > 180 and p_hp[1] < 160 and p_hp[2] < 160
            mp_ok = p_mp[2] > 180 and p_mp[0] < 100 and p_mp[1] > 80
            p_mm = frame.getpixel((30, 18))[:3]
            mm_ok = p_mm[0] > 240 and p_mm[1] > 240 and p_mm[2] > 240
            return (hp_ok and mp_ok) or (mm_ok and hp_ok)
        except Exception as err:
            _logger.debug("Error checking is_free_market: %s", err)
            return False

    def record_auction_exit(self) -> None:
        """Records timestamp when character left Auction House to disk."""
        now = time.time()
        _GLOBAL_AUCTION_EXIT_TIMES[self.device_id] = now
        _save_cooldown(self.device_id, now)
        _logger.info(
            "[%s] Recorded Auction exit (%.0f). 60s cooldown active.",
            self.device_id,
            now,
        )

    def get_auction_cooldown_remaining(
        self, cooldown_sec: float = 62.0
    ) -> float:
        """Returns remaining seconds of the 60s auction re-entry cooldown."""
        last_exit = _GLOBAL_AUCTION_EXIT_TIMES.get(self.device_id, 0.0)
        disk_cds = _load_cooldowns()
        disk_exit = disk_cds.get(self.device_id, 0.0)
        actual_last = max(last_exit, disk_exit)
        elapsed = time.time() - actual_last
        remaining = cooldown_sec - elapsed
        return max(0.0, remaining)

    def leave_auction_to_free_market(self, max_wait_sec: int = 8) -> bool:
        """Safely exits the Auction House to the Free Market."""
        if not self.is_auction_open():
            self.handle_lingering_popups()
            return True

        _logger.info(
            "[%s] Exiting Auction House to Free Market...", self.device_id
        )
        self.tap(*POS_LEAVE_AUCTION)
        self.record_auction_exit()

        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            time.sleep(0.8)
            self.handle_lingering_popups()
            if not self.is_auction_open():
                _logger.info(
                    "[%s] Successfully exited Auction House.", self.device_id
                )
                return True
        return not self.is_auction_open()

    def enter_auction_from_free_market(self, max_wait_sec: int = 12) -> bool:
        """Enters Auction House from Free Market via mobile menu."""
        remaining = self.get_auction_cooldown_remaining()
        if remaining > 0:
            _logger.info(
                "[%s] In-game cooldown active. Waiting %.1fs...",
                self.device_id,
                remaining,
            )
            time.sleep(remaining)

        self.handle_lingering_popups()
        _logger.info(
            "[%s] Opening Auction House via Free Market menu...", self.device_id
        )
        self.tap(*POS_MENU_BUTTON)
        time.sleep(0.7)
        self.tap(*POS_AUCTION_BUTTON)

        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            time.sleep(1.0)
            if self.is_auction_open():
                _logger.info(
                    "[%s] Auction House opened successfully.", self.device_id
                )
                return True
            self.handle_lingering_popups()

        _logger.warning(
            "[%s] Auction House did not open within %ds.",
            self.device_id,
            max_wait_sec,
        )
        return self.is_auction_open()


# Backward compatibility alias
AdbController = AdbDriver
