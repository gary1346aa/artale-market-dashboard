import logging
import time
from datetime import datetime, time as dtime, timedelta
from typing import Optional
from PIL import Image

from .digit_engine import parse_quota_header

logger = logging.getLogger("QuotaManager")
DEFAULT_INSTANCES = ["祈禱機", "槍手", "打火機", "弩手"]

def read_quota_from_frame(frame: Optional[Image.Image]) -> Optional[int]:
    """
    Reads in-game quota header '搜尋次數 REMAINING/TOTAL' from an Artale screen frame.
    Uses the 100% deterministic Digit Engine (zero OCR, zero hallucinations).
    Returns the remaining search count, or None if not detected.
    """
    if frame is None:
        return None
    try:
        res = parse_quota_header(frame)
        if res is not None:
            remaining, _ = res
            return remaining
    except Exception:
        pass
    return None

def get_seconds_until_next_8am() -> float:
    """Calculates seconds remaining until the next 08:00 AM server quota reset."""
    now = datetime.now()
    target = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return max(0.0, (target - now).total_seconds())

def pause_until_next_8am(instance_name: str = ""):
    """
    Pauses execution until 08:00 AM server quota reset the next day.
    Sleeps in 30-second heartbeats for clean logging.
    """
    wait_sec = get_seconds_until_next_8am()
    hours = wait_sec / 3600.0
    prefix = f"[{instance_name}] " if instance_name else ""
    logger.info(f"{prefix}Quota exhausted (< 2). Pausing instance until 08:00 AM reset ({hours:.1f} hours, {int(wait_sec)}s)...")
    wake_time = time.time() + wait_sec
    while time.time() < wake_time:
        remaining = wake_time - time.time()
        time.sleep(min(30.0, remaining))
    logger.info(f"{prefix}08:00 AM server reset reached! Resuming instance.")
