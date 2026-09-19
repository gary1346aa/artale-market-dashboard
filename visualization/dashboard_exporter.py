"""Market dashboard data exporter and HTML visualizer generator.

Extracts aggregated OHLCV candles, 24h ticker summaries, and active listings
from the database, and renders the Binance-style interactive web dashboard.
"""

import calendar
from datetime import datetime
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from config.settings import (
    ASSETS_DIR,
    DB_PATH,
    DOCS_DIR,
    PROJECT_ROOT,
    WATCHLIST_PATH,
)
from core.categories import classify_item, get_scroll_rate

_logger = logging.getLogger(__name__)

OUTPUT_HTML_PATH: Path = PROJECT_ROOT / "dashboard.html"
DOCS_HTML_PATH: Path = DOCS_DIR / "index.html"
TEMPLATE_PATH: Path = PROJECT_ROOT / "templates" / "dashboard.html.tpl"
JS_STANDALONE_PATH: Path = PROJECT_ROOT / "lightweight-charts.standalone.js"
ICON_FILE_PATH: Path = ASSETS_DIR / "icon_base64.txt"


def export_dashboard_data(
    db_path: Optional[Path] = None,
    watchlist_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Extracts candles and listings formatted for TradingView Lightweight Charts.

    Args:
        db_path: Optional custom path to SQLite database.
        watchlist_path: Optional custom path to items_watchlist.json.

    Returns:
        Dict containing 'items', 'summary', 'top_cards', and 'data'.
    """
    db_file = db_path or DB_PATH
    wl_file = watchlist_path or WATCHLIST_PATH

    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()

        if wl_file.exists():
            with open(wl_file, "r", encoding="utf-8") as f:
                raw_wl = json.load(f)
                items = sorted(
                    list(raw_wl.keys()) if isinstance(raw_wl, dict) else raw_wl
                )
        else:
            cursor.execute("SELECT DISTINCT item_name FROM kline_candles")
            items = sorted([r[0] for r in cursor.fetchall()])

        data_by_item: Dict[str, Any] = {}
        summary_list: List[Dict[str, Any]] = []

        for item in items:
            cat = classify_item(item)
            rate = get_scroll_rate(item)
            data_by_item[item] = {
                "1h": [],
                "4h": [],
                "1d": [],
                "lowest_ask": None,
            }

            for tf in ("1h", "4h", "1d"):
                cursor.execute(
                    """
                    SELECT bucket_time, open_price, high_price, low_price,
                           close_price, volume, turnover, vwap, trade_count
                    FROM kline_candles
                    WHERE item_name = ? AND timeframe = ?
                    ORDER BY bucket_time ASC
                    """,
                    (item, tf),
                )
                rows = cursor.fetchall()
                seen = set()
                for r in rows:
                    raw_t = r[0]
                    try:
                        t_val: Any = int(
                            calendar.timegm(
                                datetime.strptime(
                                    raw_t, "%Y-%m-%d %H:%M:%S"
                                ).timetuple()
                            )
                        )
                    except Exception:
                        t_val = raw_t

                    if t_val in seen:
                        continue
                    seen.add(t_val)
                    data_by_item[item][tf].append({
                        "time": t_val,
                        "open": r[1],
                        "high": r[2],
                        "low": r[3],
                        "close": r[4],
                        "volume": r[5],
                        "vwap": r[7],
                        "turnover": r[6],
                        "trades": r[8] if len(r) > 8 else 0,
                    })

            # 24h Summary calculations using 1h candles
            candles_1h = data_by_item[item]["1h"]
            if candles_1h:
                latest = candles_1h[-1]
                latest_price = latest["close"]
                latest_t = latest["time"]
                cutoff_t = latest_t - (24 * 3600)
                c24 = [c for c in candles_1h if c["time"] >= cutoff_t]

                vol_24 = sum(c["volume"] for c in c24)
                turnover_24 = sum(c["turnover"] for c in c24)
                trades_24 = sum(c["trades"] for c in c24)
                high_24 = max(c["high"] for c in c24)
                low_24 = min(c["low"] for c in c24)
                open_24 = c24[0]["open"]
                chg_24 = (
                    ((latest_price - open_24) / open_24 * 100)
                    if open_24
                    else 0.0
                )
            else:
                latest_price = 0
                vol_24 = 0
                turnover_24 = 0
                trades_24 = 0
                high_24 = 0
                low_24 = 0
                chg_24 = 0.0

            # Lowest ask with sanity threshold (>= 25% of latest price)
            min_ask_threshold = (
                (latest_price * 0.25) if latest_price > 0 else 0
            )
            cursor.execute(
                """
                SELECT min(unit_price) FROM active_listings
                WHERE item_name = ? AND unit_price >= ?
                  AND replace(captured_at, 'T', ' ') >= (
                      SELECT datetime(replace(max(captured_at), 'T', ' '), '-15 minutes')
                      FROM active_listings WHERE item_name = ?
                  )
                """,
                (item, min_ask_threshold, item),
            )
            ask_row = cursor.fetchone()
            lowest_ask = ask_row[0] if ask_row and ask_row[0] else None
            data_by_item[item]["lowest_ask"] = lowest_ask
            spread_pct = (
                ((lowest_ask - latest_price) / latest_price * 100)
                if (lowest_ask and latest_price)
                else None
            )

            data_by_item[item]["summary_24h"] = {
                "latest_price": latest_price,
                "vol_24": vol_24,
                "turnover_24": turnover_24,
                "trades_24": trades_24,
                "high_24": high_24,
                "low_24": low_24,
                "chg_24": round(chg_24, 2),
                "lowest_ask": lowest_ask,
                "spread_pct": (
                    round(spread_pct, 1) if spread_pct is not None else None
                ),
            }

            summary_list.append({
                "name": item,
                "category": cat,
                "rate": rate,
                "latest_price": latest_price,
                "chg_24": round(chg_24, 2),
                "vol_24": vol_24,
                "turnover_24": turnover_24,
                "trades_24": trades_24,
                "high_24": high_24,
                "low_24": low_24,
                "lowest_ask": lowest_ask,
                "spread_pct": (
                    round(spread_pct, 1) if spread_pct is not None else None
                ),
            })

    # Top highlight cards
    hot = sorted(
        summary_list,
        key=lambda x: (x["trades_24"], x["vol_24"]),
        reverse=True,
    )[:3]
    active_items = [
        s
        for s in summary_list
        if s["latest_price"] > 0 and s["trades_24"] > 0
    ]
    gainers = sorted(active_items, key=lambda x: x["chg_24"], reverse=True)[:3]
    turnover = sorted(
        summary_list, key=lambda x: x["turnover_24"], reverse=True
    )[:3]
    spread_items = [
        s
        for s in summary_list
        if s["spread_pct"] is not None and s["latest_price"] > 0
    ]
    spreads = sorted(spread_items, key=lambda x: x["spread_pct"])[:3]

    return {
        "items": items,
        "summary": summary_list,
        "top_cards": {
            "hot": hot,
            "gainers": gainers,
            "turnover": turnover,
            "spreads": spreads,
        },
        "data": data_by_item,
    }


def generate_dashboard_html(
    output_path: Optional[Path] = None,
    docs_path: Optional[Path] = None,
    template_path: Optional[Path] = None,
) -> Path:
    """Renders interactive SPA into dashboard.html and docs/index.html.

    Args:
        output_path: Destination path for root dashboard.html.
        docs_path: Destination path for docs/index.html (GitHub Pages).
        template_path: Template path to read HTML skeleton from.

    Returns:
        Path to the primary generated HTML file.
    """
    out_file = output_path or OUTPUT_HTML_PATH
    doc_file = docs_path or DOCS_HTML_PATH
    tpl_file = template_path or TEMPLATE_PATH

    if not tpl_file.exists():
        raise FileNotFoundError(f"Dashboard template not found at {tpl_file}")

    template = tpl_file.read_text(encoding="utf-8")

    js_code = (
        JS_STANDALONE_PATH.read_text(encoding="utf-8")
        if JS_STANDALONE_PATH.exists()
        else ""
    )
    icon_b64 = (
        ICON_FILE_PATH.read_text(encoding="utf-8").strip()
        if ICON_FILE_PATH.exists()
        else ""
    )

    payload = export_dashboard_data()
    json_str = json.dumps(payload, ensure_ascii=False)
    last_synced_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    final_html = template.replace("/*__LIGHTWEIGHT_CHARTS_JS__*/", js_code)
    final_html = final_html.replace("__PAYLOAD_JSON__", json_str)
    final_html = final_html.replace("__LAST_SYNCED__", last_synced_time)
    final_html = final_html.replace("__ICON_BASE64__", icon_b64)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(final_html, encoding="utf-8")

    doc_file.parent.mkdir(parents=True, exist_ok=True)
    doc_file.write_text(final_html, encoding="utf-8")

    _logger.info("Generated Dashboard HTML -> %s and %s", out_file, doc_file)
    return out_file
