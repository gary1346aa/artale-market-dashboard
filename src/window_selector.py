import ctypes
import ctypes.wintypes
from typing import List, Dict, Any, Optional

class WindowSelector:
    """
    Lists and selects visible top-level windows across desktops/emulators (e.g. LDPlayer, Artale).
    """

    @staticmethod
    def get_all_windows() -> List[Dict[str, Any]]:
        """
        Enumerates all visible windows with titles and valid geometry.
        """
        windows = []

        def enum_cb(hwnd, _):
            # Check visibility
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True

            # Exclude iconized / minimized or invisible parent windows
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

            # Ignore 0-sized tooltips or off-screen hidden overlays
            if w > 100 and h > 100:
                windows.append({
                    "hwnd": hwnd,
                    "title": title,
                    "x": rect.left,
                    "y": rect.top,
                    "width": w,
                    "height": h
                })
            return True

        EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        ctypes.windll.user32.EnumWindows(EnumProc(enum_cb), 0)
        return windows

    @classmethod
    def find_by_keywords(cls, keywords: List[str]) -> List[Dict[str, Any]]:
        all_wins = cls.get_all_windows()
        matches = []
        for w in all_wins:
            for kw in keywords:
                if kw.lower() in w["title"].lower():
                    matches.append(w)
                    break
        return matches

    @classmethod
    def prompt_selection(cls, keywords: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Interactive window selection CLI.
        """
        if keywords:
            candidates = cls.find_by_keywords(keywords)
        else:
            candidates = cls.get_all_windows()

        if not candidates:
            print("\n⚠️  No windows found matching default keywords (LDPlayer, MapleStory, Artale).")
            print("Showing ALL active top-level windows:")
            candidates = cls.get_all_windows()

        if not candidates:
            print("No visible windows found.")
            return None

        print("\n=======================================================")
        print("          SELECT TARGET GAME / EMULATOR WINDOW          ")
        print("=======================================================")
        for idx, win in enumerate(candidates, 1):
            print(f"  [{idx}] {win['title']} ({win['width']}x{win['height']} at {win['x']},{win['y']})")
        print("=======================================================")

        while True:
            choice = input(f"Enter window number [1-{len(candidates)}] (or 'q' to quit): ").strip()
            if choice.lower() == 'q':
                return None
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                selected = candidates[int(choice) - 1]
                print(f"Selected: '{selected['title']}' (HWND: {selected['hwnd']})")
                return selected
            print(f"Invalid input. Please enter a number between 1 and {len(candidates)}.")
