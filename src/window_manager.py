import ctypes
from typing import Optional, Tuple, List, Dict
import mss
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
            "LDPlayer", "雷電", "leidian", "dnplayer",
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
                    for kw in self.title_keywords:
                        if kw.lower() in title.lower():
                            found_hwnds.append((hwnd, title))
                            break
            return True

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        ctypes.windll.user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)

        if found_hwnds:
            self.hwnd = found_hwnds[0][0]
            return self.hwnd
        return None

    def get_window_rect(self) -> Optional[Dict[str, int]]:
        """
        Gets client bounding box (left, top, width, height) of the targeted window.
        """
        if not self.hwnd and not self.find_window():
            return None

        rect = ctypes.wintypes.RECT()
        # Use GetClientRect + ClientToScreen to avoid capturing window frame borders
        ctypes.windll.user32.GetClientRect(self.hwnd, ctypes.byref(rect))
        point = ctypes.wintypes.POINT(rect.left, rect.top)
        ctypes.windll.user32.ClientToScreen(self.hwnd, ctypes.byref(point))

        w = rect.right - rect.left
        h = rect.bottom - rect.top

        if w <= 0 or h <= 0:
            # Fallback to standard GetWindowRect
            ctypes.windll.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
            return {
                "left": rect.left,
                "top": rect.top,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top
            }

        return {
            "left": point.x,
            "top": point.y,
            "width": w,
            "height": h
        }

    def bring_to_front(self) -> bool:
        """
        Restores and focuses the game window.
        """
        if not self.hwnd and not self.find_window():
            return False

        # SW_RESTORE = 9
        ctypes.windll.user32.ShowWindow(self.hwnd, 9)
        ctypes.windll.user32.SetForegroundWindow(self.hwnd)
        return True

    def to_screen_coords(self, ref_x: int, ref_y: int) -> Optional[Tuple[int, int]]:
        """
        Converts reference coordinates (1024x576 space) into actual desktop screen coordinates.
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
