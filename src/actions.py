import time
import random
import pyautogui
import win32clipboard
import win32con

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
    for _ in range(10):
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            win32clipboard.CloseClipboard()
            return True
        except Exception:
            time.sleep(0.05)
    return False

def clear_and_paste(box_x: int, box_y: int, text: str, confirm_pt=None):
    """
    1. Clicks search box (activates LDPlayer input bar).
    2. Sends backspaces to wipe any existing content.
    3. Sets clipboard to UTF-16 Traditional Chinese text.
    4. Pastes via Ctrl+V.
    5. Sends 1 Backspace to remove LDPlayer's trailing phantom character.
    6. Sends Enter and clicks 確定 (Confirm) to commit input bar.
    7. Sends Enter again to execute game search.
    """
    # 1. Click search input box
    human_click(box_x, box_y)
    time.sleep(0.4)

    # 2. Clear input bar thoroughly
    for _ in range(50):
        pyautogui.press("backspace")
        time.sleep(0.01)
    time.sleep(0.1)

    # 3. Set clipboard
    set_clipboard_text(text.strip())
    time.sleep(0.1)

    # 4. Paste
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)

    # 5. Remove the phantom trailing glyph added by emulator clipboard sync
    pyautogui.press("backspace")
    time.sleep(0.2)

    # 6. Commit input bar via Enter and confirm button
    pyautogui.press("enter")
    time.sleep(0.3)
    if confirm_pt:
        human_click(confirm_pt[0], confirm_pt[1])
        time.sleep(0.5)

    # 7. Press Enter in game to submit search
    pyautogui.press("enter")
    time.sleep(1.5)
