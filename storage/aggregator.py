"""OHLCV candlestick aggregation engine for market trades.

Aggregates historical transaction records into standard stock-market
candlestick bars ('1h', '4h', '1d') with outlier filtering and VWAP calculation.
"""

from datetime import datetime
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from config.settings import DB_PATH
from core.models import Candle
from storage.database import get_connection, save_kline_candles

_logger = logging.getLogger(__name__)


class KlineAggregator:
    """Aggregates raw trades into stock-market OHLCV Candlesticks.

    Supported timeframes: '1h', '4h', '1d'.

    Attributes:
        db_path: Path to the SQLite database.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initializes KlineAggregator with database path."""
        self.db_path = db_path or DB_PATH

    @staticmethod
    def parse_trade_datetime(
        trade_time_str: str, captured_at_str: str = ""
    ) -> datetime:
        """Parses trade timestamps from OCR.

        Args:
            trade_time_str: Raw trade time string from OCR.
            captured_at_str: Fallback ISO string of when screen was captured.

        Returns:
            Parsed datetime object.
        """
        clean_str = trade_time_str.strip()

        # Full format: 2026-09-12 16:55 or 2026-09-12 16:55:15
        match_full = re.search(
            r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?", clean_str
        )
        if match_full:
            y, m, d, hh, mm, ss = match_full.groups()
            return datetime(int(y), int(m), int(d), int(hh), int(mm), int(ss or 0))

        # Partial format: 09-12 16:55
        match_partial = re.search(
            r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", clean_str
        )
        if match_partial:
            m, d, hh, mm = map(int, match_partial.groups())
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

    @staticmethod
    def get_bucket_timestamp(dt: datetime, timeframe: str) -> str:
        """Aligns a datetime object to the start of its interval bucket.

        Args:
            dt: Input datetime.
            timeframe: '1h', '4h', or '1d'.

        Returns:
            Formatted timestamp string 'YYYY-MM-DD HH:MM:SS'.
        """
        if timeframe == "1h":
            bucket = dt.replace(minute=0, second=0, microsecond=0)
        elif timeframe == "4h":
            bucket_hour = (dt.hour // 4) * 4
            bucket = dt.replace(
                hour=bucket_hour, minute=0, second=0, microsecond=0
            )
        elif timeframe == "1d":
            bucket = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            bucket = dt.replace(minute=0, second=0, microsecond=0)
        return bucket.strftime("%Y-%m-%d %H:%M:%S")

    def aggregate_item(
        self, item_name: str, timeframe: str = "1h"
    ) -> List[Candle]:
        """Builds OHLCV candles for a specific item over the selected timeframe.

        Args:
            item_name: Canonical item name.
            timeframe: Interval string ('1h', '4h', or '1d').

        Returns:
            List of aggregated Candle models.
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT quantity, matched_unit_price, total_matched_price,
                       trade_time, captured_at
                FROM matched_trades
                WHERE item_name = ?
                ORDER BY captured_at ASC, trade_time ASC
                """,
                (item_name,),
            )
            rows = cursor.fetchall()
            if not rows:
                return []

            # Fetch lowest active ask for recent market context
            cursor.execute(
                """
                SELECT min(unit_price) FROM active_listings
                WHERE item_name = ? AND unit_price >= 500
                  AND replace(captured_at, 'T', ' ') >= (
                      SELECT datetime(replace(max(captured_at), 'T', ' '), '-15 minutes')
                      FROM active_listings WHERE item_name = ?
                  )
                """,
                (item_name, item_name),
            )
            lowest_ask_row = cursor.fetchone()
            current_lowest_ask = (
                lowest_ask_row[0] if lowest_ask_row and lowest_ask_row[0] else None
            )

        seen_trades: Set[Tuple[str, int, int, int]] = set()
        parsed_trades: List[Dict[str, Any]] = []

        for r in rows:
            qty = r[0]
            unit_price = r[1]
            if not unit_price or unit_price < 500:
                continue
            total_price = r[2] or (qty * unit_price)
            raw_time = r[3] or ""
            cap_time = r[4] or ""

            trade_key = (raw_time, qty, unit_price, total_price)
            if trade_key in seen_trades:
                continue
            seen_trades.add(trade_key)

            trade_dt = self.parse_trade_datetime(raw_time, cap_time)
            parsed_trades.append({
                "dt": trade_dt,
                "unit_price": unit_price,
                "quantity": qty,
                "total_price": total_price,
                "raw_time": raw_time,
                "cap_time": cap_time,
            })

        parsed_trades.sort(key=lambda x: x["dt"])

        all_prices = sorted([
            t["unit_price"] for t in parsed_trades if t["unit_price"] >= 500
        ])
        global_med = all_prices[len(all_prices) // 2] if all_prices else 0

        buckets: Dict[str, List[Dict[str, Any]]] = {}
        total_trades = len(parsed_trades)

        for i, t in enumerate(parsed_trades):
            unit_price = t["unit_price"]
            trade_dt = t["dt"]

            if total_trades >= 5:
                win = [
                    parsed_trades[j]["unit_price"]
                    for j in range(max(0, i - 5), min(total_trades, i + 6))
                    if j != i and parsed_trades[j]["unit_price"] >= 500
                ]
                win_med = (
                    sorted(win)[len(win) // 2] if len(win) >= 3 else global_med
                )
                if global_med >= 500 and (
                    win_med > 1.50 * global_med or win_med < 0.65 * global_med
                ):
                    median_p = global_med
                else:
                    median_p = win_med
                low_threshold = 0.65
                high_threshold = 1.50
            else:
                median_p = global_med
                low_threshold = 0.50
                high_threshold = 1.80

            if median_p >= 500 and unit_price < median_p * low_threshold:
                continue
            if median_p >= 500 and unit_price > median_p * high_threshold:
                continue

            bucket_key = self.get_bucket_timestamp(trade_dt, timeframe)
            if bucket_key not in buckets:
                buckets[bucket_key] = []
            buckets[bucket_key].append(t)

        candles: List[Candle] = []
        for b_time in sorted(buckets.keys()):
            b_trades = buckets[b_time]
            b_trades.sort(key=lambda x: x["dt"])

            open_p = b_trades[0]["unit_price"]
            close_p = b_trades[-1]["unit_price"]
            high_p = max(trade["unit_price"] for trade in b_trades)
            low_p = min(trade["unit_price"] for trade in b_trades)
            vol = sum(trade["quantity"] for trade in b_trades)
            turnover = sum(trade["total_price"] for trade in b_trades)
            vwap = int(turnover / vol) if vol > 0 else open_p

            candle = Candle(
                item_name=item_name,
                timeframe=timeframe,
                bucket_time=b_time,
                open_price=open_p,
                high_price=high_p,
                low_price=low_p,
                close_price=close_p,
                volume=vol,
                turnover=turnover,
                vwap=vwap,
                lowest_ask=current_lowest_ask,
                trade_count=len(b_trades),
            )
            candles.append(candle)

        if candles:
            save_kline_candles(candles, db_path=self.db_path)
        return candles

    def aggregate_all_watchlist(
        self,
        watchlist: List[str],
        timeframes: Optional[List[str]] = None,
    ) -> int:
        """Builds K-line candles for all items in watchlist across timeframes.

        Args:
            watchlist: List of item names.
            timeframes: List of timeframes (defaults to ['1h', '4h', '1d']).

        Returns:
            Total count of candles generated.
        """
        tfs = timeframes or ["1h", "4h", "1d"]
        total_candles = 0
        for item in watchlist:
            for tf in tfs:
                candles = self.aggregate_item(item, timeframe=tf)
                total_candles += len(candles)
        return total_candles


def main() -> None:
    """CLI runner to aggregate all items in watchlist."""
    import json
    from config.settings import WATCHLIST_PATH, setup_logging

    setup_logging()
    if WATCHLIST_PATH.exists():
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            wl = json.load(f)
            targets = sorted(list(wl.keys())) if isinstance(wl, dict) else sorted(list(wl))
    else:
        targets = []

    agg = KlineAggregator()
    total = agg.aggregate_all_watchlist(targets)
    _logger.info(f"Aggregated {total} candles across {len(targets)} items.")


if __name__ == "__main__":
    main()

