import time
import random
import pyautogui
import pyperclip

# Enable fail-safe: slamming the mouse into any screen corner immediately halts execution
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

def human_delay(min_sec: float = 0.8, max_sec: float = 1.5):
    """
    Sleeps with a randomized duration to avoid robotic fixed-interval patterns.
    """
    time.sleep(random.uniform(min_sec, max_sec))

def human_click(x: int, y: int, jitter: int = 3):
    """
    Moves mouse with slight jitter and clicks.
    """
    target_x = x + random.randint(-jitter, jitter)
    target_y = y + random.randint(-jitter, jitter)
    duration = random.uniform(0.18, 0.35)
    
    pyautogui.moveTo(target_x, target_y, duration=duration, tween=pyautogui.easeOutQuad)
    time.sleep(random.uniform(0.05, 0.12))
    pyautogui.click()

def paste_text(text: str):
    """
    Safely pastes text using the Windows clipboard.
    Ensures Chinese characters (e.g. 頭盔, 卷軸) are accurately inputted without IME conflicts.
    """
    pyperclip.copy(text)
    time.sleep(0.08)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.1)

def clear_input():
    """
    Selects all and deletes current input box content.
    """
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.05)
    pyautogui.press("backspace")
    time.sleep(0.05)

def press_enter():
    pyautogui.press("enter")
    time.sleep(0.1)
