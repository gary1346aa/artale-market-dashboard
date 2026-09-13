import sqlite3
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path
from .database import DB_PATH, save_kline_candles

class KlineAggregator:
    """
    Transforms raw Artale transaction ledger entries (matched_trades)
    and active order books (active_listings) into stock-market OHLCV Candlesticks.
    Supported timeframes: '1h', '4h', '1d'.
    """
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH

    def parse_trade_datetime(self, trade_time_str: str, captured_at_str: str) -> datetime:
        """
        Parses trade timestamps from OCR. 
        Format in Artale is usually 'YYYY-MM-DD HH:MM' or 'MM-DD HH:MM'.
        Falls back to captured_at if unparseable.
        """
        clean_str = trade_time_str.strip()
        # Full format: 2026-09-12 16:55
        match_full = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", clean_str)
        if match_full:
            y, m, d, hh, mm = map(int, match_full.groups())
            return datetime(y, m, d, hh, mm)

        # Partial format: 09-12 16:55
        match_partial = re.search(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", clean_str)
        if match_partial:
            m, d, hh, mm = map(int, match_partial.groups())
            # Default to current year
            curr_year = datetime.now().year
            return datetime(curr_year, m, d, hh, mm)

        # Date only: 2026-09-12
        match_date = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", clean_str)
        if match_date:
            y, m, d = map(int, match_date.groups())
            return datetime(y, m, d, 0, 0)

        # Fallback to captured_at ISO timestamp
        try:
            return datetime.fromisoformat(captured_at_str)
        except Exception:
            return datetime.now()

    def get_bucket_timestamp(self, dt: datetime, timeframe: str) -> str:
        """
        Aligns a datetime object to the start of its interval bucket.
        """
        if timeframe == "1h":
            bucket = dt.replace(minute=0, second=0, microsecond=0)
        elif timeframe == "4h":
            bucket_hour = (dt.hour // 4) * 4
            bucket = dt.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)
        elif timeframe == "1d":
            bucket = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            bucket = dt.replace(minute=0, second=0, microsecond=0)
        return bucket.strftime("%Y-%m-%d %H:%M:%S")

    def aggregate_item(self, item_name: str, timeframe: str = "1h") -> List[Dict]:
        """
        Builds OHLCV candles for a specific item over the selected timeframe.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Fetch matched trades for exact item_name
            cursor.execute("""
                SELECT quantity, matched_unit_price, total_matched_price, trade_time, captured_at
                FROM matched_trades
                WHERE item_name = ?
                ORDER BY captured_at ASC, trade_time ASC
            """, (item_name,))
            rows = cursor.fetchall()

            if not rows:
                return []

            # Fetch lowest active ask for context
            cursor.execute("""
                SELECT min(unit_price) FROM active_listings
                WHERE item_name = ? AND unit_price > 0
            """, (item_name,))
            lowest_ask_row = cursor.fetchone()
            current_lowest_ask = lowest_ask_row[0] if lowest_ask_row and lowest_ask_row[0] else None

            # Calculate baseline median unit price for outlier / bundle detection
            all_prices = sorted([r[1] for r in rows if r[1] and r[1] >= 10000])
            global_med = all_prices[len(all_prices) // 2] if all_prices else 0

            # Calculate day-level medians so price trends over the week aren't falsely cut
            from collections import defaultdict
            day_prices = defaultdict(list)
            for r in rows:
                d = (r[3] or r[4] or "")[:10]
                if r[1] and r[1] >= 10000:
                    day_prices[d].append(r[1])
            day_medians = {}
            for d, pts in day_prices.items():
                day_medians[d] = sorted(pts)[len(pts) // 2] if len(pts) >= 3 else global_med

            # Bucket trades
            buckets: Dict[str, List[Dict]] = {}
            for r in rows:
                qty = r[0]
                unit_price = r[1]
                if not unit_price or unit_price < 1000:
                    continue

                raw_time = r[3] or ""
                cap_time = r[4] or ""
                trade_day = (raw_time or cap_time)[:10]
                median_p = day_medians.get(trade_day, global_med)

                # 1. Low Threshold Filter (< 70% median):
                # Catches RMT token meso, cash-settled transfers, and extreme dumping
                if median_p > 500000 and unit_price < median_p * 0.70:
                    continue

                # 2. Upper Bound Filter (> 150% median):
                # Check for legitimate multi-pack bundle, otherwise omit extreme spikes
                if median_p > 0 and unit_price > median_p * 1.50:
                    ratio = round(unit_price / median_p)
                    if 2 <= ratio <= 15:
                        norm_p = round(unit_price / ratio)
                        if 0.70 * median_p <= norm_p <= 1.50 * median_p:
                            # Legitimate multi-item bundle: normalize unit price and scale volume
                            unit_price = norm_p
                            qty = max(qty, ratio)
                        else:
                            continue
                    else:
                        # Non-bundle extreme outlier / spike (> 150% median): omit from candles
                        continue

                total_price = r[2] or (qty * unit_price)
                raw_time = r[3] or ""
                cap_time = r[4] or ""

                trade_dt = self.parse_trade_datetime(raw_time, cap_time)
                bucket_key = self.get_bucket_timestamp(trade_dt, timeframe)

                if bucket_key not in buckets:
                    buckets[bucket_key] = []
                buckets[bucket_key].append({
                    "dt": trade_dt,
                    "unit_price": unit_price,
                    "quantity": qty,
                    "total_price": total_price
                })

            candles = []
            for b_time in sorted(buckets.keys()):
                b_trades = buckets[b_time]
                # Sort trades in bucket chronologically
                b_trades.sort(key=lambda x: x["dt"])

                open_p = b_trades[0]["unit_price"]
                close_p = b_trades[-1]["unit_price"]
                high_p = max(t["unit_price"] for t in b_trades)
                low_p = min(t["unit_price"] for t in b_trades)
                vol = sum(t["quantity"] for t in b_trades)
                turnover = sum(t["total_price"] for t in b_trades)
                vwap = int(turnover / vol) if vol > 0 else open_p

                candle = {
                    "item_name": item_name,
                    "timeframe": timeframe,
                    "bucket_time": b_time,
                    "open_price": open_p,
                    "high_price": high_p,
                    "low_price": low_p,
                    "close_price": close_p,
                    "volume": vol,
                    "turnover": turnover,
                    "vwap": vwap,
                    "lowest_ask": current_lowest_ask,
                    "trade_count": len(b_trades)
                }
                candles.append(candle)

            if candles:
                save_kline_candles(candles)
            return candles

    def aggregate_all_watchlist(self, watchlist: List[str], timeframes: List[str] = ["1h", "4h", "1d"]):
        """
        Builds K-line candles for all items in watchlist across all specified timeframes.
        """
        total_candles = 0
        for item in watchlist:
            for tf in timeframes:
                candles = self.aggregate_item(item, timeframe=tf)
                total_candles += len(candles)
        return total_candles

if __name__ == "__main__":
    import json
    wl_path = Path(__file__).resolve().parent.parent / "items_watchlist.json"
    if wl_path.exists():
        with open(wl_path, "r", encoding="utf-8") as f:
            items = json.load(f)
    else:
        items = []
    
    all_targets = sorted(list(set(items)))
    agg = KlineAggregator()
    total = agg.aggregate_all_watchlist(all_targets)
    print(f"Aggregated {total} candles across {len(all_targets)} items.")
