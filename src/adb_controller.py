import subprocess
import base64
import time
import io
import logging
from typing import Optional, Tuple
from PIL import Image

logger = logging.getLogger("AdbController")

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
    POS_MENU_BUTTON = (1150, 105)
    POS_AUCTION_BUTTON = (1240, 620)

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

    def screencap(self) -> Optional[Image.Image]:
        """
        Captures the current 1280x720 display buffer directly from Android SurfaceFlinger.
        Takes ~130ms and cannot be occluded by other Windows windows.
        """
        try:
            p = subprocess.run(
                [self.adb_path, "-s", self.device_id, "exec-out", "screencap", "-p"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            if p.returncode == 0 and p.stdout:
                return Image.open(io.BytesIO(p.stdout)).convert("RGB")
        except Exception as e:
            logger.error(f"ADB screencap failed on {self.device_id}: {e}")
        return None

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
        Detected via unique bright gold/orange [ 是 ] button at (780, 480).
        """
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False
        try:
            p = frame.getpixel((780, 480))[:3]
            return (p[0] > 200 and p[1] > 140 and p[2] < 80)
        except Exception:
            return False

    def is_error_modal_open(self, frame: Optional[Image.Image] = None) -> bool:
        """
        Checks if '沒有查詢的道具。' or similar warning modal is open.
        Detected via yellow warning triangle icon at (640, 360).
        """
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False
        try:
            p = frame.getpixel((640, 360))[:3]
            return (p[0] > 220 and p[1] > 170 and p[2] < 50)
        except Exception:
            return False

    def handle_lingering_popups(self, frame: Optional[Image.Image] = None) -> bool:
        """
        Actively checks for and cancels '前往大廳' or dismisses '沒有查詢的道具' modal.
        Returns True if a popup was dismissed.
        """
        if frame is None:
            frame = self.screencap()
        if not frame:
            return False

        if self.is_lobby_dialog_open(frame):
            logger.info(f"Canceling '前往大廳' prompt on {self.device_id} via ESC...")
            self.press_esc()
            time.sleep(0.4)
            return True

        if self.is_error_modal_open(frame):
            logger.info(f"Dismissing error modal on {self.device_id} via ESC...")
            self.press_esc()
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
        Automatically cancels '前往大廳' or error popups if detected.
        """
        if frame is None:
            frame = self.screencap()
        if not frame or frame.width < 1000 or frame.height < 600:
            return False

        # If a popup was covering the auction house, dismiss it and re-capture
        if self.handle_lingering_popups(frame):
            frame = self.screencap()
            if not frame:
                return False

        try:
            # Landmark 1: White search box (280, 48)
            box_ok = any(frame.getpixel((x, 48))[0] > 180 and frame.getpixel((x, 48))[1] > 180 for x in (240, 280, 320))
            # Landmark 2: Green '開始搜尋' button around (312, 553)
            green_ok = any(frame.getpixel((x, y))[1] > 110 and frame.getpixel((x, y))[1] > frame.getpixel((x, y))[2] + 35 
                           for x in (290, 312, 335) for y in (540, 546, 552))
            # Landmark 3: Active cyan tab ('查詢' x ~ 200 or '市價' x ~ 400 at y ~ 120)
            cyan_ok = any(frame.getpixel((x, 120))[1] > 80 and frame.getpixel((x, 120))[2] > 80 and frame.getpixel((x, 120))[0] < 80
                          for x in (180, 220, 260, 360, 400, 440))
            # Landmark 4: Dark top exit button
            top_ok = any(frame.getpixel((x, 48))[0] < 60 and frame.getpixel((x, 48))[1] < 60 for x in (780, 790, 800))
            return sum([box_ok, green_ok, cyan_ok, top_ok]) >= 2
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

    def enter_auction_from_free_market(self) -> bool:
        """
        Enters the Auction House from the Free Market using the mobile menu shortcut.
        1. Tap MENU (1150, 105)
        2. Tap 拍賣場 (1240, 620)
        """
        logger.info(f"Opening Auction House from Free Market on {self.device_id}...")
        self.tap(self.POS_MENU_BUTTON[0], self.POS_MENU_BUTTON[1])
        time.sleep(0.5)
        self.tap(self.POS_AUCTION_BUTTON[0], self.POS_AUCTION_BUTTON[1])
        time.sleep(2.0)
        return self.is_auction_open()
