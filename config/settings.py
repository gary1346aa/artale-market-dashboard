"""Centralized settings and system configuration for Artale Market Tracker.

Defines all filesystem paths, emulator binary locations, canvas dimensions,
timing constants, and logging configuration in accordance with Google Python Style.
"""

from datetime import datetime, time as dtime, timedelta
import logging
import os
from pathlib import Path
import sys
from typing import Dict, List, Optional

# ==============================================================================
# Filesystem Paths
# ==============================================================================
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = PROJECT_ROOT / "data"
ASSETS_DIR: Path = PROJECT_ROOT / "assets"
FONTS_DIR: Path = ASSETS_DIR / "fonts"
DOCS_DIR: Path = PROJECT_ROOT / "docs"

# Database & Storage
DB_PATH: Path = DATA_DIR / "market.db"
WATCHLIST_PATH: Path = PROJECT_ROOT / "items_watchlist.json"
CATEGORIES_WATCHLIST_PATH: Path = PROJECT_ROOT / "categories_watchlist.json"
TEST_DATASET_DIR: Path = DATA_DIR / "test_dataset"
UNPROCESSED_CROPS_DIR: Path = DATA_DIR / "unprocessed_crops"

# Fonts
FONT_GS_PATH: Path = FONTS_DIR / "GoogleSans.ttf"
FONT_NOTO_PATH: Path = FONTS_DIR / "NotoSansTC-Medium.ttf"

# Hardware / Emulator Executable Paths
LDCONSOLE_PATH: str = r"C:\LDPlayer\LDPlayer9\ldconsole.exe"
DEFAULT_ADB_PATH: str = r"C:\LDPlayer\LDPlayer9\adb.exe"
DEFAULT_LDCONSOLE: str = LDCONSOLE_PATH
DEFAULT_ADB: str = DEFAULT_ADB_PATH
AUCTION_COOLDOWN_FILE: Path = DATA_DIR / "auction_cooldowns.json"

# ==============================================================================
# In-Game & Canvas Constants
# ==============================================================================
CANONICAL_WIDTH: int = 1280
CANONICAL_HEIGHT: int = 720
LEGACY_REF_WIDTH: int = 1024
LEGACY_REF_HEIGHT: int = 576

DAILY_SEARCH_LIMIT: int = 500
RESET_HOUR: int = 8  # Daily search quota resets at 08:00 AM server time

DEFAULT_INSTANCES: List[str] = ["祈禱機", "槍手", "打火機", "弩手"]

INSTANCE_INDEX_MAP: Dict[str, int] = {
    "祈禱機": 0,
    "槍手": 3,
    "打火機": 4,
    "弩手": 7,
}

INSTANCE_DEVICE_MAP: Dict[str, str] = {
    "槍手": "emulator-5560",
    "打火機": "emulator-5562",
    "弩手": "emulator-5568",
}

DEVICE_INSTANCE_MAP: Dict[str, str] = {
    device_id: name for name, device_id in INSTANCE_DEVICE_MAP.items()
}

# ==============================================================================
# Quota Timing Utilities
# ==============================================================================
def get_seconds_until_next_8am(
    current_time: Optional[datetime] = None,
) -> float:
    """Calculates seconds remaining until the next 08:00 AM server quota reset.

    Args:
        current_time: Optional reference datetime. Defaults to datetime.now().

    Returns:
        float: Non-negative seconds remaining until the upcoming 08:00 AM.
    """
    now = current_time or datetime.now()
    target = now.replace(hour=RESET_HOUR, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return max(0.0, (target - now).total_seconds())


# ==============================================================================
# Logging Configuration
# ==============================================================================
def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configures root logger with UTF-8 stdout streaming on Windows.

    Args:
        level: Logging level (e.g. logging.INFO, logging.DEBUG).

    Returns:
        logging.Logger: The configured root logger instance.
    """
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        force=True,
    )
    return logging.getLogger()
