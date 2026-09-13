import time
import random
import pyautogui
import win32clipboard
import win32con
import win32gui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

def human_delay(min_sec: float = 0.8, max_sec: float = 1.5):
    time.sleep(random.uniform(min_sec, max_sec))

def human_click(x: int, y: int, jitter: int = 1):
    target_x = x + random.randint(-jitter, jitter)
    target_y = y + random.randint(-jitter, jitter)
    pyautogui.moveTo(target_x, target_y, duration=0.15, tween=pyautogui.easeOutQuad)
    time.sleep(0.05)
    pyautogui.click()
    time.sleep(0.08)

def set_clipboard_text(text: str) -> bool:
    """
    Safely writes text to the Windows system clipboard and verifies
    that the clipboard actually contains the intended string before returning.
    """
    for attempt in range(25):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()

            # Read-back verification to guarantee safety
            time.sleep(0.02)
            win32clipboard.OpenClipboard()
            try:
                readback = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()

            if readback == text:
                return True
        except Exception:
            time.sleep(0.05)
    return False

def sync_clipboard_and_focus(win_mgr, text: str):
    """
    Option A: Physical mouse click out & in to force LDPlayer clipboard synchronization.
    1. Sets Windows host clipboard to text with read-back verification.
    2. Physically clicks outside LDPlayer (e.g. taskbar / screen edge) to drop LDPlayer focus.
    3. Physically clicks back onto LDPlayer title bar to regain focus.
       This real mouse focus event triggers LDPlayer's host->guest clipboard import.
    """
    clean_text = text.strip()
    if not set_clipboard_text(clean_text):
        raise RuntimeError(
            f"SECURITY / SAFETY LOCK: Refusing to paste because the Windows clipboard "
            f"could not be verified to contain '{clean_text}'."
        )
    
    import win32api
    screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    bounds = win_mgr.get_window_rect() if win_mgr else None

    # Step 1: Click outside LDPlayer to drop focus
    if bounds:
        b_left = bounds.get("left", 0)
        b_top = bounds.get("top", 50)
        b_width = bounds.get("width", 1280)
        b_right = bounds.get("right", b_left + b_width)

        if b_left > 30:
            out_x, out_y = 10, b_top + 50
        elif b_right < screen_w - 30:
            out_x, out_y = screen_w - 10, b_top + 50
        else:
            out_x, out_y = screen_w // 2, screen_h - 8
    else:
        out_x, out_y = screen_w // 2, screen_h - 8

    pyautogui.click(out_x, out_y)
    time.sleep(0.3)

    # Step 2: Click back on LDPlayer window title bar to regain focus
    if bounds:
        in_x = bounds.get("raw_left", bounds.get("left", 0)) + 250
        in_y = bounds.get("raw_top", max(0, bounds.get("top", 0) - 51)) + 15
        pyautogui.click(in_x, in_y)
    elif win_mgr:
        win_mgr.bring_to_front()
    time.sleep(0.4)

def is_input_bar_open(win_mgr) -> bool:
    """
    Checks if LDPlayer's bottom white text bar is currently active on screen.
    When active, canvas (500, 685) is solid white (255, 255, 255).
    """
    frame = win_mgr.capture_frame()
    if not frame:
        return False
    # (500, 685) on 1280x720 canvas
    try:
        p = frame.getpixel((500, 685))
        return (p[0] > 230 and p[1] > 230 and p[2] > 230)
    except Exception:
        return False

def clear_search_bar(win_mgr=None):
    """
    Triggers LDPlayer's recorded macro '刪除商城搜索列' (Alt + 8) to flawlessly
    erase any previous text in the auction search bar.
    Macro duration is 9.197 seconds.
    """
    if win_mgr:
        win_mgr.bring_to_front()
        time.sleep(0.3)
        bounds = win_mgr.get_window_rect()
        if bounds:
            cx = bounds["left"] + 640
            cy = bounds["top"] + 360
            pyautogui.click(cx, cy)
            time.sleep(0.3)
    pyautogui.hotkey("alt", "8")
    time.sleep(9.5)

def clear_and_paste(box_x: int, box_y: int, text: str, confirm_pt=None, win_mgr=None):
    """
    1. Triggers '刪除商城搜索列' (Alt + 8) to erase existing text cleanly.
    2. Syncs target text into Windows clipboard and triggers LDPlayer host->guest sync.
    3. Clicks search box to open clean bottom input bar.
    4. Pastes verified text via Ctrl+V.
    5. Removes the phantom trailing glyph.
    6. Commits input bar via Enter and 確定 button.
    7. Submits search in Artale.
    """
    # 1. Clear search bar completely using the user's recorded macro
    clear_search_bar(win_mgr=win_mgr)

    # 2. Sync Windows clipboard into LDPlayer
    clean_text = text.strip()
    if win_mgr:
        sync_clipboard_and_focus(win_mgr, clean_text)
    else:
        if not set_clipboard_text(clean_text):
            raise RuntimeError(
                f"SECURITY / SAFETY LOCK: Refusing to paste because the Windows clipboard "
                f"could not be verified to contain '{clean_text}'."
            )

    # 3. Click search input box
    human_click(box_x, box_y)
    time.sleep(0.8)

    # 3. Paste verified text
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.4)

    # 4. Remove the phantom trailing glyph added by emulator clipboard sync
    pyautogui.press("backspace")
    time.sleep(0.2)

    # 5. Commit input bar via Enter and confirm button
    pyautogui.press("enter")
    time.sleep(0.3)
    if confirm_pt:
        human_click(confirm_pt[0], confirm_pt[1])
        time.sleep(0.6)

    # 6. Press Enter in game to submit search
    pyautogui.press("enter")
    time.sleep(1.5)



