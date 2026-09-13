import subprocess
import time
import logging
from pathlib import Path
from typing import Optional
import pyautogui

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
        """
        frame = win_mgr.capture_frame()
        if not frame or frame.width < 500 or frame.height < 300:
            return False
        try:
            # Multi-landmark verification:
            # 1. Dark gray top modal border at (640, 50)
            top_p = frame.getpixel((640, 50))[:3]
            top_ok = abs(top_p[0] - top_p[1]) <= 5 and abs(top_p[1] - top_p[2]) <= 5 and 40 <= top_p[0] <= 60

            # 2. Dark gray table header at (955, 155)
            hdr_p = frame.getpixel((955, 155))[:3]
            hdr_ok = abs(hdr_p[0] - hdr_p[1]) <= 5 and abs(hdr_p[1] - hdr_p[2]) <= 5 and 25 <= hdr_p[0] <= 45

            # 3. Cyan tab indicator at (244, 90) or (320, 90)
            t1 = frame.getpixel((244, 90))[:3]
            t2 = frame.getpixel((320, 90))[:3]
            tab_ok = (t1[1] > 100 and t1[2] > 100) or (t2[1] > 100 and t2[2] > 100)

            return top_ok and hdr_ok and tab_ok
        except Exception:
            return False

    def ensure_instance_in_auction(self, instance_name: str, max_macro_wait: int = 320) -> bool:
        """
        Ensures that the specified instance is running and currently parked inside the Auction House.
        If not yet in the auction, triggers '開遊戲到拍賣場.record' via Alt + 9 and waits for completion.
        """
        # 1. Ensure emulator is running
        if not self.launch_instance(instance_name):
            return False

        # 2. Find and focus window
        win_mgr = WindowManager(title_keywords=[instance_name])
        hwnd = win_mgr.find_window()
        if not hwnd:
            logger.error(f"Could not find window HWND for instance '{instance_name}'.")
            return False

        win_mgr.bring_to_front()
        time.sleep(1.0)

        # 3. Check if already inside Auction House
        if self.is_auction_open(win_mgr):
            logger.info(f"Instance '{instance_name}' is already verified inside the Auction House.")
            return True

        # 4. Trigger recorded macro: Alt + 9
        logger.info(f"Instance '{instance_name}' is not in the Auction House. Triggering '開遊戲到拍賣場' (Alt + 9)...")
        bounds = win_mgr.get_window_rect()
        if bounds:
            title_x = bounds.get("raw_left", bounds["left"]) + 200
            title_y = bounds.get("raw_top", bounds["top"]) + 20
            pyautogui.click(title_x, title_y)
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
