import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import json
import sqlite3
import logging
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TierEvaluator")

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "market.db"
WATCHLIST_PATH = PROJECT_DIR / "items_watchlist.json"

TIER_SPECS = {
    1: {"name": "Ultra-High", "poll_interval_hours": 2.0, "desc": "極高頻消耗品/礦石 (每 1~2 小時)"},
    2: {"name": "High", "poll_interval_hours": 6.0, "desc": "高頻衝卷/廣播 (每 4~6 小時)"},
    3: {"name": "Moderate", "poll_interval_hours": 12.0, "desc": "主流飾品/武器卷 (每 12 小時)"},
    4: {"name": "Low / Sparse", "poll_interval_hours": 24.0, "desc": "冷門與長尾卷軸 (每 24 小時+)"},
}

class TierEvaluator:
    """
    Evaluates item trading velocity from market.db and directly updates
    items_watchlist.json with the calculated tier and latest update timestamp,
    preserving the existing item order.
    """
    BUFFER_CAPACITY = 100.0  # Safe threshold before in-game AH history rolls off (~120-140)

    def __init__(self, db_path: Optional[Path] = None, watchlist_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.watchlist_path = watchlist_path or WATCHLIST_PATH

    def load_raw_watchlist(self) -> Tuple[List[str], Dict[str, Dict]]:
        """
        Loads items_watchlist.json preserving original item ordering.
        Returns:
            order: List of item names in original sequence.
            data: Dict mapping item_name to its dict { "tier": int, "last_updated": str | None }
        """
        if not self.watchlist_path.exists():
            return [], {}

        with open(self.watchlist_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        order = []
        data = {}
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
                        "last_updated": v.get("last_updated")
                    }
                elif isinstance(v, int):
                    data[k] = {"tier": v, "last_updated": None}
                else:
                    data[k] = {"tier": 3, "last_updated": None}
        return order, data

    def classify_tier(self, peak_hr: int, daily_avg: float, safe_overflow_hrs: float) -> int:
        """
        Assigns tier 1, 2, 3, or 4 based on peak velocity and safe overflow threshold.
        """
        if safe_overflow_hrs <= 3.5 or peak_hr >= 28:
            return 1
        elif safe_overflow_hrs <= 8.5 or peak_hr >= 12 or daily_avg >= 35.0:
            return 2
        elif safe_overflow_hrs <= 24.0 or peak_hr >= 4 or daily_avg >= 10.0:
            return 3
        else:
            return 4

    def evaluate_item_velocity(self, item_name: str, cursor: sqlite3.Cursor) -> Tuple[int, Optional[str]]:
        """
        Queries matched_trades & active_listings for item_name and calculates (tier, latest_captured_at).
        """
        cursor.execute("""
            SELECT trade_time, captured_at
            FROM matched_trades
            WHERE item_name = ?
            ORDER BY trade_time ASC
        """, (item_name,))
        rows = cursor.fetchall()

        # Find latest capture timestamp across matched_trades and active_listings
        latest_cap_at = None
        for r in rows:
            if r[1] and (latest_cap_at is None or r[1] > latest_cap_at):
                latest_cap_at = r[1]

        cursor.execute("SELECT max(captured_at) FROM active_listings WHERE item_name = ?", (item_name,))
        ask_row = cursor.fetchone()
        if ask_row and ask_row[0]:
            if latest_cap_at is None or ask_row[0] > latest_cap_at:
                latest_cap_at = ask_row[0]

        if not rows:
            clean_ts = self._format_timestamp(latest_cap_at)
            return 4, clean_ts

        total_trades = len(rows)
        hour_counts = defaultdict(int)
        day_counts = defaultdict(int)

        for trade_time, _ in rows:
            if trade_time and len(trade_time) >= 13:
                hour_counts[trade_time[:13]] += 1
            if trade_time and len(trade_time) >= 10:
                day_counts[trade_time[:10]] += 1

        peak_hr = max(hour_counts.values()) if hour_counts else 0
        active_days = len(day_counts) if day_counts else 1
        daily_avg = total_trades / active_days

        safe_overflow_hrs = (self.BUFFER_CAPACITY / peak_hr) if peak_hr > 0 else 999.0
        tier = self.classify_tier(peak_hr, daily_avg, safe_overflow_hrs)
        clean_ts = self._format_timestamp(latest_cap_at)

        return tier, clean_ts

    def _format_timestamp(self, ts_str: Optional[str]) -> Optional[str]:
        if not ts_str:
            return None
        try:
            # Handle ISO string (e.g. 2026-09-14T03:13:05.559504)
            dt = datetime.fromisoformat(ts_str)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(ts_str)[:19].replace("T", " ")

    def evaluate_and_update_watchlist(self) -> Dict:
        """
        Evaluates all items in items_watchlist.json, updates their tier and last_updated,
        and saves back maintaining the EXACT original item ordering.
        """
        order, existing_data = self.load_raw_watchlist()
        if not order:
            logger.warning("Watchlist is empty or file not found.")
            return {}

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            tier_counts = defaultdict(int)
            promotions = []
            demotions = []
            updated_watchlist = {}

            for item in order:
                old_tier = existing_data.get(item, {}).get("tier", 3)
                new_tier, latest_db_ts = self.evaluate_item_velocity(item, cursor)

                last_updated = existing_data.get(item, {}).get("last_updated") or latest_db_ts

                if old_tier and new_tier < old_tier:
                    promotions.append((item, old_tier, new_tier))
                elif old_tier and new_tier > old_tier:
                    demotions.append((item, old_tier, new_tier))

                updated_watchlist[item] = {
                    "tier": new_tier,
                    "last_updated": last_updated
                }
                tier_counts[new_tier] += 1

        # Write back preserving the exact item ordering
        with open(self.watchlist_path, "w", encoding="utf-8") as f:
            json.dump(updated_watchlist, f, ensure_ascii=False, indent=2)

        logger.info(f"Updated items_watchlist.json with {len(updated_watchlist)} items (Order preserved).")
        logger.info(f"Tier Distribution: T1={tier_counts[1]}, T2={tier_counts[2]}, T3={tier_counts[3]}, T4={tier_counts[4]}")
        if promotions:
            logger.info(f"Promotions ({len(promotions)}): " + ", ".join(f"{p[0]} (T{p[1]}->T{p[2]})" for p in promotions[:5]))
        if demotions:
            logger.info(f"Demotions ({len(demotions)}): " + ", ".join(f"{d[0]} (T{d[1]}->T{d[2]})" for d in demotions[:5]))

        return {
            "total_items": len(updated_watchlist),
            "tier_counts": dict(tier_counts),
            "promotions": promotions,
            "demotions": demotions
        }

    def get_due_items(self) -> Tuple[List[str], float, Optional[str]]:
        """
        Scans items_watchlist.json against each item's tier polling interval.
        Returns:
            due_items: List of item names currently due for collection.
            min_wait_seconds: Seconds until the next item becomes due.
            next_due_item: Name of the item that will become due earliest.
        """
        order, data = self.load_raw_watchlist()
        now = datetime.now()
        due_items = []
        next_waits = []

        for item in order:
            info = data.get(item, {})
            tier = info.get("tier", 3)
            interval_hours = TIER_SPECS.get(tier, {}).get("poll_interval_hours", 12.0)
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

def update_item_timestamp(item_name: str, watchlist_path: Optional[Path] = None):
    """
    Utility function called by the collector when an item is collected.
    Updates the item's last_updated timestamp in items_watchlist.json in-place.
    """
    wl_file = watchlist_path or WATCHLIST_PATH
    if not wl_file.exists():
        return
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
    except Exception as e:
        logger.debug(f"Could not update timestamp for '{item_name}': {e}")

def get_due_items(watchlist_path: Optional[Path] = None) -> Tuple[List[str], float, Optional[str]]:
    """
    Convenience wrapper to get due items and next schedule wait time.
    """
    evaluator = TierEvaluator(watchlist_path=watchlist_path)
    return evaluator.get_due_items()

if __name__ == "__main__":
    evaluator = TierEvaluator()
    evaluator.evaluate_and_update_watchlist()
    due, wait_sec, next_it = evaluator.get_due_items()
    print(f"\nCurrently Due: {len(due)} items")
    if next_it:
        print(f"Next Due Item: '{next_it}' in {wait_sec/60:.1f} minutes")
