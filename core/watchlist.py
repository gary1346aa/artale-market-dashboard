"""Thread-safe watchlist management and priority tier evaluation.

Analyzes trading velocity from market.db and manages items_watchlist.json
to balance polling frequency against the 500-search daily quota limit.
"""

from collections import defaultdict
from datetime import datetime
import json
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

from config.settings import DB_PATH, WATCHLIST_PATH

_logger = logging.getLogger(__name__)
_WATCHLIST_LOCK = threading.Lock()

# Standard priority tier definitions
TIER_SPECS: Dict[int, Dict[str, Any]] = {
    1: {
        "name": "Ultra-High",
        "poll_interval_hours": 20.0 / 60.0,
        "desc": "極高頻消耗品/礦石 (每 20 分鐘)",
    },
    2: {
        "name": "High",
        "poll_interval_hours": 4.0,
        "desc": "高頻衝卷/廣播 (每 4 小時)",
    },
    3: {
        "name": "Moderate",
        "poll_interval_hours": 12.0,
        "desc": "主流飾品/武器卷 (每 12 小時)",
    },
    4: {
        "name": "Low / Sparse",
        "poll_interval_hours": 24.0,
        "desc": "冷門與長尾卷軸 (每 24 小時+)",
    },
}

BUFFER_CAPACITY: float = 100.0


class WatchlistManager:
    """Manages watchlist loading, updates, and tier evaluation.

    Attributes:
        db_path: Path to the SQLite database.
        watchlist_path: Path to the JSON watchlist catalog.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        watchlist_path: Optional[Path] = None,
    ) -> None:
        """Initializes the WatchlistManager with paths."""
        self.db_path = db_path or DB_PATH
        self.watchlist_path = watchlist_path or WATCHLIST_PATH

    def load_raw_watchlist(self) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
        """Loads items_watchlist.json preserving original item ordering.

        Returns:
            A tuple of:
                - order: List of item names in original sequence.
                - data: Dict mapping item_name to dict containing 'tier' and 'last_updated'.
        """
        if not self.watchlist_path.exists():
            return [], {}

        with _WATCHLIST_LOCK:
            with open(self.watchlist_path, "r", encoding="utf-8") as f:
                raw = json.load(f)

        order: List[str] = []
        data: Dict[str, Dict[str, Any]] = {}

        if isinstance(raw, list):
            for item in raw:
                order.append(item)
                data[item] = {"tier": 3, "last_updated": None}
        elif isinstance(raw, dict):
            for k, v in raw.items():
                order.append(k)
                if isinstance(v, dict):
                    data[k] = {
                        "tier": v.get("tier", 3),
                        "last_updated": v.get("last_updated"),
                    }
                elif isinstance(v, int):
                    data[k] = {"tier": v, "last_updated": None}
                else:
                    data[k] = {"tier": 3, "last_updated": None}
        return order, data

    @staticmethod
    def classify_tier(
        peak_hr: int, daily_avg: float, safe_overflow_hrs: float
    ) -> int:
        """Assigns priority tier 1 to 4 based on trade velocity.

        Args:
            peak_hr: Maximum trades observed in any single hour.
            daily_avg: Average trades per active day.
            safe_overflow_hrs: Hours before 100-record buffer rolls off.

        Returns:
            Calculated tier integer (1, 2, 3, or 4).
        """
        if safe_overflow_hrs <= 3.5 or peak_hr >= 28:
            return 1
        if safe_overflow_hrs <= 8.5 or peak_hr >= 12 or daily_avg >= 35.0:
            return 2
        if safe_overflow_hrs <= 24.0 or peak_hr >= 4 or daily_avg >= 10.0:
            return 3
        return 4

    def evaluate_item_velocity(
        self,
        item_name: str,
        cursor: sqlite3.Cursor,
        current_tier: int = 3,
    ) -> Tuple[int, Optional[str]]:
        """Calculates trading velocity and returns calculated tier and last update.

        Args:
            item_name: In-game item name.
            cursor: Open SQLite cursor.
            current_tier: Existing tier configuration fallback.

        Returns:
            Tuple of (tier, latest_captured_at_string).
        """
        cursor.execute(
            """
            SELECT trade_time, captured_at
            FROM matched_trades
            WHERE item_name = ?
            ORDER BY trade_time ASC
            """,
            (item_name,),
        )
        rows = cursor.fetchall()

        latest_cap_at: Optional[str] = None
        for r in rows:
            if r[1] and (latest_cap_at is None or r[1] > latest_cap_at):
                latest_cap_at = r[1]

        cursor.execute(
            "SELECT max(captured_at) FROM active_listings WHERE item_name = ?",
            (item_name,),
        )
        ask_row = cursor.fetchone()
        if ask_row and ask_row[0]:
            if latest_cap_at is None or ask_row[0] > latest_cap_at:
                latest_cap_at = ask_row[0]

        if not rows:
            return current_tier, self._format_timestamp(latest_cap_at)

        hour_counts: Dict[str, int] = defaultdict(int)
        day_counts: Dict[str, int] = defaultdict(int)

        for trade_time, _ in rows:
            if trade_time and len(trade_time) >= 13:
                hour_counts[trade_time[:13]] += 1
            if trade_time and len(trade_time) >= 10:
                day_counts[trade_time[:10]] += 1

        peak_hr = max(hour_counts.values()) if hour_counts else 0
        active_days = len(day_counts) if day_counts else 1
        daily_avg = len(rows) / active_days

        safe_overflow_hrs = (BUFFER_CAPACITY / peak_hr) if peak_hr > 0 else 999.0
        tier = self.classify_tier(peak_hr, daily_avg, safe_overflow_hrs)
        return tier, self._format_timestamp(latest_cap_at)

    @staticmethod
    def _format_timestamp(ts_str: Optional[str]) -> Optional[str]:
        """Formats ISO timestamp strings to 'YYYY-MM-DD HH:MM:SS'."""
        if not ts_str:
            return None
        try:
            dt = datetime.fromisoformat(ts_str)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(ts_str)[:19].replace("T", " ")

    def evaluate_and_update_watchlist(self) -> Dict[str, Any]:
        """Evaluates all items in the watchlist and updates their tiers in-place.

        Returns:
            Dictionary summarizing total items, tier counts, promotions, and demotions.
        """
        order, existing_data = self.load_raw_watchlist()
        if not order:
            _logger.warning("Watchlist is empty or file not found.")
            return {}

        tier_counts: Dict[int, int] = defaultdict(int)
        promotions: List[Tuple[str, int, int]] = []
        demotions: List[Tuple[str, int, int]] = []
        updated_watchlist: Dict[str, Dict[str, Any]] = {}

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for item in order:
                old_tier = existing_data.get(item, {}).get("tier", 3)
                new_tier, latest_db_ts = self.evaluate_item_velocity(
                    item, cursor, current_tier=old_tier
                )
                last_updated = (
                    existing_data.get(item, {}).get("last_updated") or latest_db_ts
                )

                if old_tier and new_tier < old_tier:
                    promotions.append((item, old_tier, new_tier))
                elif old_tier and new_tier > old_tier:
                    demotions.append((item, old_tier, new_tier))

                updated_watchlist[item] = {
                    "tier": new_tier,
                    "last_updated": last_updated,
                }
                tier_counts[new_tier] += 1

        with _WATCHLIST_LOCK:
            with open(self.watchlist_path, "w", encoding="utf-8") as f:
                json.dump(updated_watchlist, f, ensure_ascii=False, indent=2)

        _logger.info(
            f"Updated {self.watchlist_path.name} with {len(updated_watchlist)} items (Order preserved)."
        )
        return {
            "total_items": len(updated_watchlist),
            "tier_counts": dict(tier_counts),
            "promotions": promotions,
            "demotions": demotions,
        }

    def get_due_items(self) -> Tuple[List[str], float, Optional[str]]:
        """Scans the watchlist against each item's tier polling interval.

        Returns:
            A tuple of:
                - due_items: List of item names currently due for collection.
                - min_wait_seconds: Seconds until the next item becomes due.
                - next_due_item: Name of the item that will become due earliest.
        """
        order, data = self.load_raw_watchlist()
        now = datetime.now()
        due_items: List[str] = []
        next_waits: List[Tuple[str, float]] = []

        for item in order:
            info = data.get(item, {})
            tier = info.get("tier", 3)
            interval_hours = TIER_SPECS.get(tier, {}).get(
                "poll_interval_hours", 12.0
            )
            last_str = info.get("last_updated")

            if not last_str:
                due_items.append(item)
                continue

            try:
                dt = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    dt = datetime.fromisoformat(last_str)
                except Exception:
                    due_items.append(item)
                    continue

            elapsed_seconds = (now - dt).total_seconds()
            target_seconds = interval_hours * 3600.0

            if elapsed_seconds >= target_seconds:
                due_items.append(item)
            else:
                remaining = target_seconds - elapsed_seconds
                next_waits.append((item, remaining))

        if next_waits:
            min_item, min_sec = min(next_waits, key=lambda x: x[1])
        else:
            min_item, min_sec = None, 1800.0

        return due_items, min_sec, min_item


# Backward compatibility alias
TierEvaluator = WatchlistManager


def update_item_timestamp(
    item_name: str, watchlist_path: Optional[Path] = None
) -> None:
    """Updates the item's last_updated timestamp in items_watchlist.json in-place.

    Args:
        item_name: Exact name of the item collected.
        watchlist_path: Optional custom path to items_watchlist.json.
    """
    wl_file = watchlist_path or WATCHLIST_PATH
    if not wl_file.exists():
        return

    with _WATCHLIST_LOCK:
        try:
            with open(wl_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(raw, dict) and item_name in raw:
                if isinstance(raw[item_name], dict):
                    raw[item_name]["last_updated"] = now_str
                else:
                    raw[item_name] = {"tier": raw[item_name], "last_updated": now_str}
                with open(wl_file, "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)
        except Exception as err:
            _logger.debug(f"Could not update timestamp for '{item_name}': {err}")


def get_due_items(
    watchlist_path: Optional[Path] = None,
) -> Tuple[List[str], float, Optional[str]]:
    """Convenience helper to retrieve due items and next schedule wait time.

    Args:
        watchlist_path: Optional custom path to items_watchlist.json.

    Returns:
        Tuple of (due_items, wait_seconds, next_item_name).
    """
    manager = WatchlistManager(watchlist_path=watchlist_path)
    return manager.get_due_items()


def get_item_last_updated(
    item_name: str, watchlist_path: Optional[Path] = None
) -> str:
    """Retrieves the last_updated timestamp for the item from items_watchlist.json.

    Args:
        item_name: Name of the item.
        watchlist_path: Optional custom path to items_watchlist.json.

    Returns:
        Formatted timestamp string, or current time if not found.
    """
    wl_file = watchlist_path or WATCHLIST_PATH
    if wl_file.exists():
        try:
            with open(wl_file, "r", encoding="utf-8") as f:
                wl = json.load(f)
            if isinstance(wl, dict) and item_name in wl:
                val = wl[item_name]
                if isinstance(val, dict) and val.get("last_updated"):
                    return str(val["last_updated"])
        except Exception as err:
            _logger.debug(f"Error reading last_updated for '{item_name}': {err}")
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
