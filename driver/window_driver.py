"""Win32 window discovery, coordinate scaling, and frame capture driver.

Provides DPI-aware window search, client geometry calculation, and desktop
screen capture via mss for host-level automation and fallbacks.
"""

import ctypes
import ctypes.wintypes
import logging
from typing import Any, Dict, List, Optional, Tuple

import mss
from PIL import Image

_logger = logging.getLogger(__name__)


def enable_dpi_awareness() -> None:
    """Enables Windows process DPI awareness (Per-Monitor v2 or System)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class WindowSelector:
    """Enumerates and selects visible top-level windows on Windows."""

    @staticmethod
    def get_all_windows() -> List[Dict[str, Any]]:
        """Enumerates all visible windows with titles and valid geometry.

        Returns:
            List of dicts containing 'hwnd', 'title', 'x', 'y', 'width', 'height'.
        """
        enable_dpi_awareness()
        windows: List[Dict[str, Any]] = []

        def enum_cb(hwnd: int, _: Any) -> bool:
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True

            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True

            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()

            if not title:
                return True

            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top

            if w > 100 and h > 100:
                windows.append({
                    "hwnd": hwnd,
                    "title": title,
                    "x": rect.left,
                    "y": rect.top,
                    "width": w,
                    "height": h,
                })
            return True

        enum_proc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )
        ctypes.windll.user32.EnumWindows(enum_proc(enum_cb), 0)
        return windows

    @classmethod
    def find_by_keywords(cls, keywords: List[str]) -> List[Dict[str, Any]]:
        """Finds visible windows matching any title keyword.

        Args:
            keywords: List of keyword substrings to match case-insensitively.

        Returns:
            List of matching window info dicts.
        """
        all_wins = cls.get_all_windows()
        matches: List[Dict[str, Any]] = []
        for w in all_wins:
            for kw in keywords:
                if kw.lower() in w["title"].lower():
                    matches.append(w)
                    break
        return matches


class WindowManager:
    """Manages window discovery, coordinate scaling, and frame capture.

    Attributes:
        hwnd: Target window handle.
        title_keywords: Window title keywords used for discovery.
    """

    REF_WIDTH = 1280
    REF_HEIGHT = 720

    def __init__(
        self,
        title_keywords: Optional[List[str]] = None,
        target_hwnd: Optional[int] = None,
    ) -> None:
        """Initializes WindowManager."""
        self.title_keywords = title_keywords or [
            "祈禱機",
            "LDPlayer",
            "雷電",
            "leidian",
            "dnplayer",
            "Artale",
            "MapleStory",
            "MapleStory Worlds",
            "MSW",
        ]
        self.hwnd: Optional[int] = target_hwnd
        self._sct = mss.mss()
        enable_dpi_awareness()

    def set_hwnd(self, hwnd: int) -> None:
        """Sets target window handle directly."""
        self.hwnd = hwnd

    def find_window(self) -> Optional[int]:
        """Searches for active game or emulator window matching title keywords.

        Returns:
            HWND integer if found, or None.
        """
        matches = WindowSelector.find_by_keywords(self.title_keywords)
        if matches:
            self.hwnd = matches[0]["hwnd"]
            return self.hwnd
        return None

    def get_window_rect(self) -> Optional[Dict[str, int]]:
        """Calculates client bounding box of the targeted window.

        Returns:
            Dict of 'left', 'top', 'width', 'height' or None.
        """
        if not self.hwnd and not self.find_window():
            return None

        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top

        # Standard LDPlayer 9 title bar ~51px
        if h >= 740 or w >= 1300:
            top_bar_offset = 51
            return {
                "left": rect.left,
                "top": rect.top + top_bar_offset,
                "width": 1280,
                "height": 720,
            }

        return {
            "left": rect.left,
            "top": rect.top,
            "width": w,
            "height": h,
        }

    def capture_frame(self) -> Optional[Image.Image]:
        """Captures window client area using mss desktop screen grabber.

        Returns:
            PIL RGB Image or None on failure.
        """
        rect = self.get_window_rect()
        if not rect:
            return None

        try:
            monitor = {
                "top": rect["top"],
                "left": rect["left"],
                "width": rect["width"],
                "height": rect["height"],
            }
            sct_img = self._sct.grab(monitor)
            return Image.frombytes(
                "RGB", sct_img.size, sct_img.bgra, "raw", "BGRX"
            )
        except Exception as err:
            _logger.error(f"Failed to capture window frame: {err}")
            return None
