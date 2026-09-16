import subprocess
import time
import logging
from pathlib import Path
from typing import Optional
import pyautogui
from PIL import Image, ImageChops, ImageStat

from .window_manager import WindowManager

logger = logging.getLogger("artale_tracker")
LDCONSOLE = r"C:\LDPlayer\LDPlayer9\ldconsole.exe"

class InstanceLauncher:
    """
    Manages LDPlayer instance lifecycle and automated navigation into the Artale Auction House.
    """
    def __init__(self, ldconsole_path: str = LDCONSOLE):
        self.ldconsole = ldconsole_path

    def is_running(self, instance_name: str) -> bool:
        try:
            res = subprocess.run([self.ldconsole, "isrunning", "--name", instance_name], capture_output=True, text=True)
            return res.stdout.strip() == "running"
        except Exception as e:
            logger.error(f"Error checking instance state for '{instance_name}': {e}")
            return False

    def launch_instance(self, instance_name: str, max_wait_sec: int = 50) -> bool:
        """
        Boots the instance via ldconsole and waits for Android OS to stabilize.
        """
        if self.is_running(instance_name):
            logger.info(f"Instance '{instance_name}' is already running.")
            return True

        logger.info(f"Booting LDPlayer instance '{instance_name}'...")
        subprocess.run([self.ldconsole, "launch", "--name", instance_name], capture_output=True, text=True)

        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            if self.is_running(instance_name):
                logger.info(f"Instance '{instance_name}' reported 'running'. Waiting 16s for Android launcher to settle...")
                time.sleep(16)
                return True
            time.sleep(2)

        logger.error(f"Timed out waiting for '{instance_name}' to boot.")
        return False

    def is_auction_open(self, win_mgr: WindowManager) -> bool:
        """
        Verifies if the Artale Auction House UI is currently open on screen.
        Uses robust multi-landmark scoring across invariant UI elements:
        1. Free Market Minimap is covered (not bright white at 30, 18)
        2. Bright green '開始搜尋' button in left sidebar (280..340, 535..558)
        3. Dark gray exit button container with white text '離開' at (975..1040, 32..48)
        4. Dark frame corner at (100, 120)
        """
        frame = win_mgr.capture_frame()
        if not frame or frame.width < 500 or frame.height < 300:
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
            logger.error(f"Error in launcher is_auction_open: {e}")
            return False

    def is_free_market(self, win_mgr: WindowManager) -> bool:
        """
        Verifies if the character is currently standing in the Artale Free Market (自由市場).
        Uses template matching on the '自由市場' map name at top-left and MapleStory in-game HUD landmarks.
        """
        frame = win_mgr.capture_frame()
        if not frame or frame.width < 500 or frame.height < 300:
            return False
        try:
            # 1. Template comparison with assets/free_market_indicator.png
            tpl_path = Path(__file__).resolve().parent.parent / "assets" / "free_market_indicator.png"
            if tpl_path.exists():
                tpl = Image.open(tpl_path).convert("RGB")
                crop = frame.crop((50, 50, 140, 75)).convert("RGB")
                diff = ImageChops.difference(crop, tpl)
                diff_score = sum(ImageStat.Stat(diff).mean)
                if diff_score < 40.0:
                    return True

            # 2. Backup check: HP/MP status bar at bottom center and minimap header
            p_hp = frame.getpixel((600, 647))[:3]
            p_mp = frame.getpixel((600, 668))[:3]
            hp_ok = (p_hp[0] > 180 and p_hp[1] < 160 and p_hp[2] < 160)
            mp_ok = (p_mp[2] > 180 and p_mp[0] < 100 and p_mp[1] > 80)

            p_mm = frame.getpixel((30, 18))[:3]
            mm_ok = (p_mm[0] > 240 and p_mm[1] > 240 and p_mm[2] > 240)

            return hp_ok and mp_ok and mm_ok
        except Exception as e:
            logger.debug(f"Error checking Free Market: {e}")
            return False

    def ensure_instance_in_auction(self, instance_name: str, max_macro_wait: int = 320) -> bool:
        """
        Ensures that the specified instance is running and currently parked inside the Auction House.
        If verified inside Free Market, triggers Alt + 7.
        If on Home Screen or other screen, skips Alt + 7 and executes '開遊戲到拍賣場.record' via Alt + 9.
        """
        # 1. Quick check: Is the window already open and inside Auction House?
        win_mgr = WindowManager(title_keywords=[instance_name, "LDPlayer", "雷電模擬器", "雷電"])
        hwnd = win_mgr.find_window()
        if hwnd:
            win_mgr.bring_to_front()
            time.sleep(0.5)
            if self.is_auction_open(win_mgr):
                logger.info(f"Instance '{instance_name}' is already verified inside the Auction House.")
                return True

        # 2. Ensure emulator is running
        if not self.launch_instance(instance_name):
            return False

        # 3. Find and focus window after boot
        hwnd = win_mgr.find_window()
        if not hwnd:
            logger.error(f"Could not find window HWND for instance '{instance_name}'.")
            return False

        win_mgr.bring_to_front()
        time.sleep(1.0)

        # 4. Check if inside Auction House
        if self.is_auction_open(win_mgr):
            logger.info(f"Instance '{instance_name}' is already verified inside the Auction House.")
            return True

        # 4. Strictly check screen: ONLY execute Alt + 7 if standing in Free Market!
        if self.is_free_market(win_mgr):
            logger.info(f"Instance '{instance_name}' is verified in the FREE MARKET (自由市場). Triggering quick recovery (Alt + 7)...")
            win_mgr.bring_to_front()
            time.sleep(0.5)

            pyautogui.hotkey("alt", "7")
            for _ in range(8):
                time.sleep(2)
                if self.is_auction_open(win_mgr):
                    logger.info(f"SUCCESS: Instance '{instance_name}' reached Auction House via Alt + 7!")
                    return True

            # If Alt + 7 didn't open, dismiss possible modal dialogs (e.g. NPC or "在此地圖內無法使用")
            logger.warning(f"Alt + 7 did not open Auction House immediately. Attempting to dismiss possible dialogs (ESC/Space)...")
            pyautogui.press("esc")
            time.sleep(1.0)
            pyautogui.press("space")
            time.sleep(1.0)
            pyautogui.hotkey("alt", "7")
            for _ in range(8):
                time.sleep(2)
                if self.is_auction_open(win_mgr):
                    logger.info(f"SUCCESS: Instance '{instance_name}' reached Auction House via Alt + 7 after dismissing dialogs!")
                    return True

            logger.error(f"STRICT SAFETY: Instance '{instance_name}' is still in Free Market. Alt + 9 is ONLY valid on Home Page and will NOT be run in-game.")
            return False
        else:
            # 5. Only if outside Artale / on Android Home Screen: execute '開遊戲到拍賣場' (Alt + 9)
            logger.info(f"Instance '{instance_name}' is outside Artale / on Home Screen. Alt + 7 is skipped.")
            logger.info(f"Triggering Home Page recovery '開遊戲到拍賣場' (Alt + 9)...")
            win_mgr.bring_to_front()
            time.sleep(0.5)

            pyautogui.hotkey("alt", "9")
            logger.info(f"Sent Alt + 9. Waiting up to {max_macro_wait}s for macro to enter Auction House...")

            start_t = time.time()
            # Poll every 10s after an initial 60s
            time.sleep(60)
            while time.time() - start_t < max_macro_wait:
                win_mgr.bring_to_front()
                if self.is_auction_open(win_mgr):
                    elapsed = int(time.time() - start_t)
                    logger.info(f"SUCCESS: Instance '{instance_name}' reached Auction House after {elapsed}s!")
                    return True
                time.sleep(10)

            logger.error(f"Failed to reach Auction House on '{instance_name}' within {max_macro_wait}s.")
            return False
