import ctypes
import ctypes.wintypes
from typing import Optional, Tuple, List, Dict
import mss
import time
import pyautogui
from PIL import Image

class WindowManager:
    """
    Manages MapleStory Worlds / Artale window discovery, coordinate scaling, and frame capture.
    Reference resolution: 1024 x 576.
    """
    REF_WIDTH = 1024
    REF_HEIGHT = 576

    def __init__(self, title_keywords: Optional[List[str]] = None, target_hwnd: Optional[int] = None):
        self.title_keywords = title_keywords or [
            "祈禱機", "LDPlayer", "雷電", "leidian", "dnplayer",
            "Artale", "MapleStory", "MapleStory Worlds", "MSW"
        ]
        self.hwnd: Optional[int] = target_hwnd
        self.sct = mss.mss()
        self._enable_dpi_awareness()

    def set_hwnd(self, hwnd: int):
        self.hwnd = hwnd

    def _enable_dpi_awareness(self):
        try:
            # Per-monitor DPI awareness v2 or system DPI aware
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    def find_window(self) -> Optional[int]:
        """
        Searches for the active Artale / MapleStory Worlds game window.
        """
        found_hwnds = []

        def enum_windows_callback(hwnd, extra):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
                    title = buffer.value

                    # Ignore Windows File Explorer, CMD, and terminal windows
                    class_buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetClassNameW(hwnd, class_buf, 256)
                    cls_name = class_buf.value
                    if cls_name in ("CabinetWClass", "ExploreWClass", "ConsoleWindowClass"):
                        return True
                    if "market_tracker" in title.lower() or "cmd.exe" in title.lower():
                        return True

                    for kw in self.title_keywords:
                        if kw.lower() in title.lower():
                            found_hwnds.append((hwnd, title, kw))
                            break
            return True

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        ctypes.windll.user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)

        if found_hwnds:
            # Prioritize exact instance name match (first title_keyword) over generic emulator titles
            found_hwnds.sort(key=lambda x: 0 if (self.title_keywords and x[2] == self.title_keywords[0]) else 1)
            self.hwnd = found_hwnds[0][0]
            return self.hwnd
        return None

    def get_window_rect(self) -> Optional[Dict[str, int]]:
        """
        Gets client bounding box (left, top, width, height) of the targeted window.
        Accounts for LDPlayer's 51px top title bar and 57px right toolbar.
        """
        if not self.hwnd and not self.find_window():
            return None

        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top

        # LDPlayer emulator detection (standard LD9 window has title bar ~51px and toolbar ~57px)
        if h >= 740 or w >= 1300:
            top_bar_offset = 51
            game_w = 1280
            game_h = 720
            return {
                "left": rect.left,
                "top": rect.top + top_bar_offset,
                "width": game_w,
                "height": game_h,
                "right": rect.left + game_w,
                "bottom": rect.top + top_bar_offset + game_h,
                "raw_left": rect.left,
                "raw_top": rect.top,
                "raw_right": rect.right,
                "raw_bottom": rect.bottom,
                "raw_width": w,
                "raw_height": h
            }

        return {
            "left": rect.left,
            "top": rect.top,
            "width": w,
            "height": h,
            "right": rect.right,
            "bottom": rect.bottom
        }

    def bring_to_front(self) -> bool:
        """
        Restores and focuses the game window.
        """
        if not self.hwnd and not self.find_window():
            return False

        ctypes.windll.user32.ShowWindow(self.hwnd, 9)  # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(self.hwnd)
        
        # Pop above all other windows, then clear topmost flag so user isn't locked
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_SHOWWINDOW = 0x0040
        ctypes.windll.user32.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        ctypes.windll.user32.SetWindowPos(self.hwnd, -2, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        ctypes.windll.user32.BringWindowToTop(self.hwnd)

        # Physically click title bar to guarantee Windows foreground activation over File Explorer / CMD
        bounds = self.get_window_rect()
        if bounds:
            title_x = bounds.get("raw_left", bounds.get("left", 0)) + 250
            title_y = bounds.get("raw_top", max(0, bounds.get("top", 0) - 51)) + 15
            try:
                pyautogui.click(title_x, title_y)
                time.sleep(0.3)
            except Exception:
                pass

        return True

    def to_screen_coords(self, ref_x: int, ref_y: int) -> Optional[Tuple[int, int]]:
        """
        Converts reference coordinates (1024x576 space) into actual desktop screen coordinates.
        Scales precisely onto the inner 1280x720 game canvas.
        """
        bounds = self.get_window_rect()
        if not bounds:
            return None

        scale_x = bounds["width"] / self.REF_WIDTH
        scale_y = bounds["height"] / self.REF_HEIGHT

        screen_x = int(bounds["left"] + ref_x * scale_x)
        screen_y = int(bounds["top"] + ref_y * scale_y)
        return (screen_x, screen_y)

    def capture_frame(self) -> Optional[Image.Image]:
        """
        Captures the current client window area and returns a PIL Image.
        """
        bounds = self.get_window_rect()
        if not bounds:
            return None

        monitor = {
            "top": bounds["top"],
            "left": bounds["left"],
            "width": bounds["width"],
            "height": bounds["height"]
        }

        sct_img = self.sct.grab(monitor)
        # Convert raw BGRA bytes to PIL Image (RGB)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        return img

    def capture_ld_screencap(self, wait_banner_seconds: float = 8.0) -> Optional[Image.Image]:
        """
        Triggers LDPlayer's official Ctrl + 0 screenshot feature to get an un-occluded,
        pixel-perfect 1280x720 emulator frame.
        
        SAFETY GUARD:
        LDPlayer displays a top notification banner upon screenshot ("Screenshot saved...").
        We enforce an 8-second delay after the shortcut to allow the banner to dismiss
        completely before performing subsequent clicks, preventing accidental album preview switches.
        """
        import time
        from pathlib import Path
        import pyautogui

        pic_dir = Path(r"C:\Users\gary1\Documents\XuanZhi9\Pictures\Screenshots")
        before_files = set(pic_dir.glob("*.png")) if pic_dir.exists() else set()

        if not self.bring_to_front():
            return None
        time.sleep(0.3)

        bounds = self.get_window_rect()
        if bounds:
            cx = bounds["left"] + 640
            cy = bounds["top"] + 360
            pyautogui.click(cx, cy)
            time.sleep(0.2)

        pyautogui.hotkey("ctrl", "0")
        time.sleep(1.0)

        # Retrieve newly generated screenshot
        img = None
        after_files = set(pic_dir.glob("*.png")) if pic_dir.exists() else set()
        new_files = sorted(list(after_files - before_files), key=lambda f: f.stat().st_mtime, reverse=True)
        if new_files:
            try:
                img = Image.open(new_files[0]).convert("RGB")
            except Exception:
                pass

        # Wait for top notification banner to fade out completely
        if wait_banner_seconds > 1.0:
            time.sleep(wait_banner_seconds - 1.0)

        return img
