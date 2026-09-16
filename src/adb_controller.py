import subprocess
import base64
import time
import io
import os
import json
import logging
from typing import Optional, Tuple, Dict, List, Union
from PIL import Image

logger = logging.getLogger("AdbController")

_GLOBAL_AUCTION_EXIT_TIMES: Dict[str, float] = {}
COOLDOWN_FILE = os.path.join("data", "auction_cooldowns.json")

def _load_cooldowns() -> Dict[str, float]:
    try:
        if os.path.exists(COOLDOWN_FILE):
            with open(COOLDOWN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_cooldown(device_id: str, ts: float):
    try:
        os.makedirs("data", exist_ok=True)
        cd = _load_cooldowns()
        cd[device_id] = ts
        with open(COOLDOWN_FILE, "w", encoding="utf-8") as f:
            json.dump(cd, f, indent=2)
    except Exception as e:
        logger.debug(f"Could not save auction cooldown to disk: {e}")

class AdbController:
    """
    High-performance, background ADB driver for LDPlayer instances.
    Enables zero-focus, zero-mouse-interference game automation with direct 1280x720 canvas coordinates.
    """
    DEFAULT_ADB = r"C:\LDPlayer\LDPlayer9\adb.exe"

    POS_QUICK_SEARCH = (280, 40)
    POS_CONFIRM_INPUT = (1185, 685)
    POS_QUERY_TAB = (244, 90)
    POS_MARKET_TAB = (522, 90)
    POS_PRICE_HEADER = (945, 170)
    POS_NEXT_PAGE = (850, 140)
    POS_FIRST_PAGE = (666, 140)
    POS_MENU_BUTTON = (1171, 116)
    POS_AUCTION_BUTTON = (1239, 616)
    POS_LEAVE_AUCTION = (1015, 45)
    POS_CONFIRM_EXIT = (635, 615)
    POS_STOP_DIALOG = (349, 461)

    @classmethod
    def list_attached_devices(cls, adb_path: str = DEFAULT_ADB) -> List[str]:
        """Returns list of all attached and responsive ADB devices."""
        try:
            p = subprocess.run([adb_path, "devices"], capture_output=True, text=True, timeout=5)
            devs = []
            for line in p.stdout.splitlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    devs.append(parts[0])
            return devs
        except Exception as e:
            logger.error(f"Error listing attached ADB devices: {e}")
            return []

    def __init__(self, device_id: str = "emulator-5558", adb_path: str = DEFAULT_ADB):
        self.device_id = device_id
        self.adb_path = adb_path
        self._ensure_adb_keyboard()

    def _run_adb(self, *args, check: bool = False) -> subprocess.CompletedProcess:
        cmd = [self.adb_path, "-s", self.device_id] + list(args)
        return subprocess.run(cmd, capture_output=True, check=check)

    def _ensure_adb_keyboard(self):
        """Verifies and enables ADBKeyBoard IME."""
        try:
            self._run_adb("shell", "ime", "enable", "com.android.adbkeyboard/.AdbIME")
            self._run_adb("shell", "ime", "set", "com.android.adbkeyboard/.AdbIME")
        except Exception as e:
            logger.warning(f"Could not auto-enable ADBKeyBoard on {self.device_id}: {e}")

    def screencap(
        self,
        crop: Optional[Tuple[int, int, int, int]] = None,
        as_jpeg: bool = False,
        jpeg_quality: int = 85
    ) -> Optional[Image.Image]:
        """
        Captures the display buffer via high-performance RAW SurfaceFlinger dump.
        Avoids Android-side PNG compression overhead (~3x faster, ~110-125ms total).
        If crop=(x1, y1, x2, y2) is provided, directly slices the memory buffer BEFORE
        image instantiation and JPEG encoding, optimizing both memory and speed.
        Returns PIL RGB Image.
        """
        try:
            p = subprocess.run(
                [self.adb_path, "-s", self.device_id, "exec-out", "screencap"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2.0
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
                        crop_bytes = b"".join(data[16 + y * stride + x1 * 4 : 16 + y * stride + x2 * 4] for y in range(y1, y2))
                        img = Image.frombytes("RGBA", (cw, ch), crop_bytes, "raw", "RGBA").convert("RGB")
                    else:
                        img = Image.frombytes("RGBA", (w, h), data[16:16 + expected], "raw", "RGBA").convert("RGB")

                    if as_jpeg:
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=jpeg_quality)
                        buf.seek(0)
                        return Image.open(buf)
                    return img
        except Exception as e:
            logger.debug(f"ADB raw screencap failed on {self.device_id}: {e}")

        # Resilient fallback: standard PNG screencap
        try:
            p = subprocess.run(
                [self.adb_path, "-s", self.device_id, "exec-out", "screencap", "-p"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2.0
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
        except Exception as e:
            logger.error(f"ADB fallback screencap failed on {self.device_id}: {e}")
        return None

    def save_screencap_jpg(
        self,
        filepath: Union[str, any],
        crop: Optional[Tuple[int, int, int, int]] = None,
        quality: int = 85
    ) -> bool:
        """
        Convenience method to capture, crop in-memory, and write a compact JPEG directly to disk
        for rapid visual verification during development.
        """
        img = self.screencap(crop=crop, as_jpeg=True, jpeg_quality=quality)
        if img:
            img.save(str(filepath), format="JPEG", quality=quality)
            return True
        return False

    def tap(self, x: int, y: int):
        """Taps the exact canvas coordinate on screen without moving host mouse."""
        self._run_adb("shell", "input", "tap", str(int(x)), str(int(y)))

    def keyevent(self, code: int):
        """Sends an Android keyevent (e.g. 111 for ESC, 66 for ENTER)."""
        self._run_adb("shell", "input", "keyevent", str(code))

    def press_esc(self):
        self.keyevent(111)

    def press_enter(self):
        self.keyevent(66)

    def is_lobby_dialog_open(self, frame: Optional[Image.Image] = None) -> bool:
        """
        Checks if '前往大廳 是否結束遊玩並前往大廳？' exit dialog is open.
        Accurately detected by the prominent orange confirmation button around (741, 490)
        and gray [ 否 ] button around (481, 490).
        """
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False
        try:
            p_yes = frame.getpixel((741, 490))[:3]
            is_orange = (p_yes[0] > 220 and 140 < p_yes[1] < 210 and p_yes[2] < 80)
            p_no = frame.getpixel((481, 490))[:3]
            is_gray = (p_no[0] > 180 and p_no[1] > 180 and p_no[2] > 180) or (abs(p_no[0] - p_no[1]) < 10 and abs(p_no[1] - p_no[2]) < 10 and 40 < p_no[0] < 160)
            return is_orange and is_gray
        except Exception:
            return False

    def is_error_modal_open(self, frame: Optional[Image.Image] = None) -> bool:
        """
        Checks if '沒有查詢的道具。' or similar warning modal is open.
        Detected via yellow warning triangle icon at (635, 365) AND cyan box border at (640, 420).
        """
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False
        try:
            p_tri = frame.getpixel((635, 365))[:3]
            has_tri = (p_tri[0] > 220 and p_tri[1] > 170 and p_tri[2] < 50)
            p_cyan = frame.getpixel((640, 420))[:3]
            has_cyan = (p_cyan[1] > 110 and p_cyan[2] > 120 and p_cyan[0] < 60)
            return has_tri and has_cyan
        except Exception:
            return False

    def is_exit_cooldown_dialog_open(self, frame: Optional[Image.Image] = None) -> bool:
        """
        Checks if '退出後需等待一段時間才能再進入，請稍後再試。' notice is open after leaving auction.
        Detected via confirm button around (815, 450) and blue modal background around (600, 300).
        """
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False
        try:
            p_btn = frame.getpixel((815, 450))[:3]
            btn_ok = (70 <= p_btn[0] <= 130 and 30 <= p_btn[1] <= 80 and p_btn[2] <= 50)
            p_bg = frame.getpixel((600, 300))[:3]
            bg_ok = (20 <= p_bg[0] <= 65 and 40 <= p_bg[1] <= 95 and 60 <= p_bg[2] <= 130)
            return btn_ok and bg_ok
        except Exception:
            return False

    def is_npc_dialog_open(self, frame: Optional[Image.Image] = None) -> bool:
        """
        Checks if an NPC dialogue (e.g. 璐璐 / 水晶商店) with [停止對話] is open in Free Market.
        Detected via green button around (349, 461) and grey dialog box at (500, 300).
        """
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False
        try:
            p_btn = frame.getpixel((349, 461))[:3]
            btn_ok = (p_btn[1] > 160 and p_btn[1] >= p_btn[0] and p_btn[1] > p_btn[2] + 40)
            p_bg = frame.getpixel((500, 300))[:3]
            bg_ok = (p_bg[0] > 220 and p_bg[1] > 220 and p_bg[2] > 220)
            return btn_ok and bg_ok
        except Exception:
            return False

    def handle_lingering_popups(self, frame: Optional[Image.Image] = None) -> bool:
        """
        Actively checks for and dismisses:
        1. '前往大廳' prompt (via tapping [ 否 ])
        2. Exit cooldown modal '退出後需等待一段時間...' (via tapping [ 確定 ])
        3. Free Market NPC dialog '歡迎來到 Artale...' (via tapping [ 停止對話 ])
        4. Warning modal '沒有查詢的道具。' / '請求已取消。' (via neutral tap)
        """
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False

        if self.is_lobby_dialog_open(frame):
            logger.info(f"Dismissing '前往大廳' prompt on {self.device_id} by tapping [ 否 ]...")
            self.tap(481, 490)
            time.sleep(0.4)
            return True

        if self.is_exit_cooldown_dialog_open(frame):
            logger.info(f"Dismissing auction exit cooldown notice on {self.device_id} by tapping [ 確定 ]...")
            self.tap(*self.POS_CONFIRM_EXIT)
            time.sleep(0.4)
            return True

        if self.is_npc_dialog_open(frame):
            logger.info(f"Dismissing Free Market NPC dialogue on {self.device_id} by tapping [ 停止對話 ]...")
            self.tap(*self.POS_STOP_DIALOG)
            time.sleep(0.4)
            return True

        if self.is_error_modal_open(frame):
            logger.info(f"Dismissing warning/error modal on {self.device_id} via neutral tap...")
            self.tap(640, 420)
            time.sleep(0.4)
            return True

        return False

    def input_chinese(self, text: str):
        """
        Injects Chinese/Unicode text into the active input field via ADBKeyBoard.
        Takes <50ms, zero host clipboard reliance, zero phantom glyphs.
        """
        clean_text = text.strip()
        # Clear existing text
        self._run_adb("shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT")
        time.sleep(0.05)
        # Broadcast Base64 encoded UTF-8 string
        b64 = base64.b64encode(clean_text.encode('utf-8')).decode('ascii')
        self._run_adb("shell", "am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", b64)
        time.sleep(0.15)

    def is_auction_open(self, frame: Optional[Image.Image] = None) -> bool:
        """
        Verifies if the Auction House modal is currently open.
        Automatically cancels popups/dialogs if detected.
        """
        if frame is None:
            frame = self.screencap()
        if not frame or frame.width < 1000 or frame.height < 600:
            return False

        # Dismiss any covering popup first
        if self.handle_lingering_popups(frame):
            frame = self.screencap()
            if not frame:
                return False

        try:
            # 1. Minimap check: In Free Market / World, minimap at (30, 18) is bright white (> 200, > 200, > 200)
            p_mm = frame.getpixel((30, 18))[:3]
            if p_mm[0] > 200 and p_mm[1] > 200 and p_mm[2] > 200:
                return False

            # 2. Sidebar green '開始搜尋' button: x in 280..340, y in 535..558
            green_count = sum(1 for x in range(280, 340, 5) for y in range(535, 558, 3) 
                              if frame.getpixel((x, y))[1] > 130 and frame.getpixel((x, y))[0] > 100 
                              and frame.getpixel((x, y))[2] < 70 and frame.getpixel((x, y))[1] > frame.getpixel((x, y))[0] + 15)
            green_ok = green_count >= 5

            # 3. Top-right '離開' button dark container with white text
            p_leave_bg = frame.getpixel((975, 40))[:3]
            bg_ok = (20 <= p_leave_bg[0] <= 55 and 20 <= p_leave_bg[1] <= 55 and 20 <= p_leave_bg[2] <= 55)
            text_count = sum(1 for x in range(990, 1040, 3) for y in range(32, 48, 2)
                             if all(c > 170 for c in frame.getpixel((x, y))[:3]))
            leave_ok = bg_ok and text_count >= 4

            # 4. Auction house header tab area (100, 120) dark frame
            p_hdr = frame.getpixel((100, 120))[:3]
            hdr_ok = (p_hdr[0] < 70 and p_hdr[1] < 70 and p_hdr[2] < 70)

            return sum([green_ok, leave_ok, hdr_ok]) >= 2
        except Exception as e:
            logger.debug(f"Error checking is_auction_open: {e}")
            return False

    def is_free_market(self, frame: Optional[Image.Image] = None) -> bool:
        """
        Verifies if character is standing in the Free Market map.
        """
        if frame is None:
            frame = self.screencap()
        if not frame or frame.width < 1000 or frame.height < 600:
            return False
        try:
            p_hp = frame.getpixel((600, 647))[:3]
            p_mp = frame.getpixel((600, 668))[:3]
            hp_ok = (p_hp[0] > 180 and p_hp[1] < 160 and p_hp[2] < 160)
            mp_ok = (p_mp[2] > 180 and p_mp[0] < 100 and p_mp[1] > 80)
            p_mm = frame.getpixel((30, 18))[:3]
            mm_ok = (p_mm[0] > 240 and p_mm[1] > 240 and p_mm[2] > 240)
            return (hp_ok and mp_ok) or (mm_ok and hp_ok)
        except Exception as e:
            logger.debug(f"Error checking is_free_market: {e}")
            return False

    def record_auction_exit(self):
        """Records timestamp when character left the Auction House to memory and disk."""
        now = time.time()
        _GLOBAL_AUCTION_EXIT_TIMES[self.device_id] = now
        _save_cooldown(self.device_id, now)
        logger.info(f"[{self.device_id}] Recorded Auction exit timestamp ({now:.0f}). 60-second cooldown initiated.")

    def get_auction_cooldown_remaining(self, cooldown_sec: float = 62.0) -> float:
        """Returns remaining seconds of the 60s in-game auction re-entry cooldown (with 2s safety buffer)."""
        last_exit = _GLOBAL_AUCTION_EXIT_TIMES.get(self.device_id, 0.0)
        disk_cds = _load_cooldowns()
        disk_exit = disk_cds.get(self.device_id, 0.0)
        actual_last = max(last_exit, disk_exit)
        elapsed = time.time() - actual_last
        remaining = cooldown_sec - elapsed
        return max(0.0, remaining)

    def leave_auction_to_free_market(self, max_wait_sec: int = 8) -> bool:
        """
        Taps [離開 >] button at (1015, 45) to safely exit the Auction House,
        dismisses the exit cooldown notice / NPC dialogue,
        and records the exit timestamp for the 60-second re-entry cooldown.
        """
        if not self.is_auction_open():
            self.handle_lingering_popups()
            return True

        logger.info(f"[{self.device_id}] Exiting Auction House to Free Market to prevent idle timeout...")
        self.tap(*self.POS_LEAVE_AUCTION)
        self.record_auction_exit()

        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            time.sleep(0.8)
            self.handle_lingering_popups()
            if not self.is_auction_open():
                logger.info(f"[{self.device_id}] Successfully exited Auction House to Free Market.")
                return True
        return not self.is_auction_open()

    def enter_auction_from_free_market(self, max_wait_sec: int = 12) -> bool:
        """
        Enters the Auction House from the Free Market using the mobile menu shortcut.
        1. Checks and waits out the 60-second in-game cooldown if recently exited.
        2. Clears any blocking NPC dialogue or popups.
        3. Taps MENU (1171, 116) -> 拍賣場 (1239, 616).
        4. Polls progressively up to max_wait_sec instead of failing prematurely.
        """
        # 1. Enforce 60s re-entry cooldown gate
        remaining = self.get_auction_cooldown_remaining()
        if remaining > 0:
            logger.info(f"[{self.device_id}] In-game auction cooldown active. Waiting {remaining:.1f}s before entering...")
            time.sleep(remaining)

        # Clear any lingering NPC dialogs / popups blocking the screen
        self.handle_lingering_popups()

        logger.info(f"[{self.device_id}] Opening Auction House via Free Market menu...")
        self.tap(*self.POS_MENU_BUTTON)
        time.sleep(0.7)
        self.tap(*self.POS_AUCTION_BUTTON)

        # 2. Progressive polling window (up to max_wait_sec)
        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            time.sleep(1.0)
            if self.is_auction_open():
                logger.info(f"[{self.device_id}] Auction House opened successfully.")
                return True
            self.handle_lingering_popups()

        logger.warning(f"[{self.device_id}] Auction House did not open within {max_wait_sec}s.")
        return self.is_auction_open()
