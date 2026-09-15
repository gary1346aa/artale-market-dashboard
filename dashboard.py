import sqlite3
import json
import webbrowser
import calendar
from datetime import datetime
from pathlib import Path
from typing import List, Dict

DB_PATH = Path(__file__).resolve().parent / "data" / "market.db"
OUTPUT_HTML = Path(__file__).resolve().parent / "dashboard.html"
DOCS_DIR = Path(__file__).resolve().parent / "docs"
DOCS_HTML = DOCS_DIR / "index.html"
WATCHLIST_FILE = Path(__file__).resolve().parent / "items_watchlist.json"
JS_STANDALONE = Path(__file__).resolve().parent / "lightweight-charts.standalone.js"

def classify_item(name: str) -> str:
    skill_keywords = ['楓葉祝福', '挑釁', '技能書', '母書']
    if any(k in name for k in skill_keywords):
        return '技能書'
    cash_keywords = ['喇叭', '瞬移', '突襲', '背包', '護身符', '初始化', '加持器', '漫天花雨', '飄雪結晶']
    if any(k in name for k in cash_keywords):
        return '現金道具'
    acc_keywords = ['墜飾', '眼部裝飾', '臉部裝飾', '耳環', '戒指', '腰帶']
    if any(k in name for k in acc_keywords):
        return '飾品卷'
    weapon_keywords = ['拳套', '弓', '弩', '單手劍', '雙手劍', '矛', '槍', '短劍', '手套攻擊力', '指虎', '火槍', '短杖', '長杖']
    if any(k in name for k in weapon_keywords):
        return '武器卷'
    armor_keywords = ['頭盔', '鞋子', '手套']
    if any(k in name for k in armor_keywords):
        return '防具卷'
    material_keywords = ['時間碎片', '母礦', '水晶']
    if any(k in name for k in material_keywords):
        return '材料'
    return '其他'

def get_scroll_rate(name: str) -> str:
    for r in ['100%', '70%', '60%', '30%', '10%']:
        if r in name:
            return r
    return '-'

def export_dashboard_data() -> Dict:
    """
    Extracts all candles and active listings from market.db formatted for the Binance overview
    and TradingView Lightweight Charts.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        if WATCHLIST_FILE.exists():
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                raw_wl = json.load(f)
                items = sorted(list(raw_wl.keys()) if isinstance(raw_wl, dict) else raw_wl)
        else:
            cursor.execute("SELECT DISTINCT item_name FROM kline_candles")
            items = sorted([r[0] for r in cursor.fetchall()])

        data_by_item = {}
        summary_list = []

        for item in items:
            cat = classify_item(item)
            rate = get_scroll_rate(item)
            data_by_item[item] = {"1h": [], "4h": [], "1d": [], "lowest_ask": None}

            # Fetch candles for each timeframe
            for tf in ["1h", "4h", "1d"]:
                cursor.execute("""
                    SELECT bucket_time, open_price, high_price, low_price, close_price, volume, turnover, vwap, trade_count
                    FROM kline_candles
                    WHERE item_name = ? AND timeframe = ?
                    ORDER BY bucket_time ASC
                """, (item, tf))
                rows = cursor.fetchall()
                seen = set()
                for r in rows:
                    raw_t = r[0]
                    try:
                        # Use calendar.timegm so Lightweight Charts UTC getters render the exact game clock hour
                        t_val = int(calendar.timegm(datetime.strptime(raw_t, "%Y-%m-%d %H:%M:%S").timetuple()))
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
                        "trades": r[8] if len(r) > 8 else 0
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
                chg_24 = ((latest_price - open_24) / open_24 * 100) if open_24 else 0.0
            else:
                latest_price = 0
                vol_24 = 0
                turnover_24 = 0
                trades_24 = 0
                high_24 = 0
                low_24 = 0
                chg_24 = 0.0

            # Lowest ask with sanity threshold (>= 25% of latest price)
            min_ask_threshold = (latest_price * 0.25) if latest_price > 0 else 0
            cursor.execute("""
                SELECT min(unit_price) FROM active_listings
                WHERE item_name = ? AND unit_price >= ?
            """, (item, min_ask_threshold))
            ask_row = cursor.fetchone()
            lowest_ask = ask_row[0] if ask_row and ask_row[0] else None
            data_by_item[item]["lowest_ask"] = lowest_ask

            spread_pct = ((lowest_ask - latest_price) / latest_price * 100) if (lowest_ask and latest_price) else None

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
                "spread_pct": round(spread_pct, 1) if spread_pct is not None else None
            })

    # Top highlight cards
    hot = sorted(summary_list, key=lambda x: (x["trades_24"], x["vol_24"]), reverse=True)[:3]
    active_items = [s for s in summary_list if s["latest_price"] > 0 and s["trades_24"] > 0]
    gainers = sorted(active_items, key=lambda x: x["chg_24"], reverse=True)[:3]
    turnover = sorted(summary_list, key=lambda x: x["turnover_24"], reverse=True)[:3]
    spread_items = [s for s in summary_list if s["spread_pct"] is not None and s["latest_price"] > 0]
    spreads = sorted(spread_items, key=lambda x: x["spread_pct"])[:3]

    return {
        "items": items,
        "summary": summary_list,
        "top_cards": {
            "hot": hot,
            "gainers": gainers,
            "turnover": turnover,
            "spreads": spreads
        },
        "data": data_by_item
    }

def generate_dashboard_html():
    """
    Renders an interactive Binance-Style Market Overview & TradingView Candlestick SPA into dashboard.html and docs/index.html.
    All text strictly uses Google-Sans.
    """
    if JS_STANDALONE.exists():
        with open(JS_STANDALONE, "r", encoding="utf-8") as f:
            js_code = f.read()
    else:
        js_code = ""

    payload = export_dashboard_data()
    json_str = json.dumps(payload, ensure_ascii=False)
    last_synced_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Template using token replacement to avoid f-string escaping pitfalls
    template = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Artale Market - 市場總覽 & 行情圖表</title>
    <link rel="icon" type="image/png" href="data:image/png;base64,__ICON_BASE64__">
    <!-- Google Sans Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Google+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400;1,700&family=Google+Sans+Text:ital,wght@0,400;0,500;0,600;0,700;1,400;1,700&family=Noto+Sans+TC:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script>/*__LIGHTWEIGHT_CHARTS_JS__*/</script>
    <style>
        :root {
            --font-family: 'Google Sans', 'Google Sans Text', 'Noto Sans TC', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            --bg-main: #0b0e14;
            --bg-card: #181a20;
            --bg-card-hover: #222634;
            --bg-sub: #131722;
            --border-color: #262b36;
            --border-subtle: #1e222d;
            --text-main: #eaecef;
            --text-sub: #848e9c;
            --text-dim: #5e6673;
            --accent-blue: #2962ff;
            --accent-gold: #f0b90b;
            --c-up: #0ecb81;
            --c-down: #f6465d;
            --c-ask: #ff9800;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: var(--font-family) !important;
            -webkit-tap-highlight-color: transparent;
        }

        html, body {
            height: 100%;
            height: 100dvh;
            background-color: var(--bg-main);
            color: var(--text-main);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            user-select: none;
            -webkit-user-select: none;
        }

        /* Top Header Navigation */
        .app-header {
            background-color: var(--bg-card);
            padding: 10px 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-bottom: 1px solid var(--border-color);
            flex-shrink: 0;
            z-index: 20;
            width: 100%;
        }

        .header-inner {
            width: 100%;
            max-width: 1240px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
        }

        .brand-box {
            display: flex;
            align-items: center;
            gap: 10px;
            cursor: pointer;
            transition: opacity 0.15s ease;
        }

        .brand-box:hover {
            opacity: 0.88;
        }

        .brand-logo-img {
            width: 34px;
            height: 34px;
            object-fit: contain;
            display: block;
            filter: drop-shadow(0 2px 5px rgba(0, 0, 0, 0.45));
            transition: transform 0.2s ease;
        }

        .brand-box:hover .brand-logo-img {
            transform: scale(1.1) rotate(-3deg);
        }

        .brand-logo {
            font-size: 1.35rem;
            line-height: 1;
        }

        .brand-title {
            font-size: 1.12rem;
            font-weight: 700;
            letter-spacing: -0.2px;
            color: #ffffff;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .header-status {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.78rem;
            color: var(--text-sub);
        }

        .status-dot {
            width: 7px;
            height: 7px;
            background-color: var(--c-up);
            border-radius: 50%;
            display: inline-block;
        }

        /* Main View Containers */
        .view-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-height: 0;
            overflow: hidden;
        }

        /* ----------------------------------------------------
           OVERVIEW VIEW (#view-overview)
           ---------------------------------------------------- */
        #view-overview {
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
            padding: 20px 24px 48px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .overview-content {
            width: 100%;
            max-width: 1240px;
            display: flex;
            flex-direction: column;
            gap: 18px;
        }

        /* Top 4 Summary Cards */
        .top-cards-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 14px;
            flex-shrink: 0;
            width: 100%;
        }

        .summary-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            min-width: 0;
            transition: border-color 0.2s ease, transform 0.15s ease;
        }

        .summary-card:hover {
            border-color: #3b4252;
        }

        .card-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--border-subtle);
            padding-bottom: 7px;
        }

        .card-title {
            font-size: 0.82rem;
            font-weight: 700;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .card-tag {
            font-size: 0.68rem;
            color: var(--text-dim);
            font-weight: 500;
        }

        .card-list {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .card-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 6px 8px;
            border-radius: 6px;
            cursor: pointer;
            gap: 8px;
            transition: background-color 0.15s ease;
        }

        .card-row:hover {
            background-color: var(--bg-card-hover);
        }

        .card-row-left {
            display: flex;
            flex-direction: column;
            gap: 2px;
            flex: 1;
            min-width: 0;
        }

        .card-row-title-box {
            display: flex;
            align-items: center;
            gap: 6px;
            min-width: 0;
            width: 100%;
        }

        .card-row-name {
            font-size: 0.82rem;
            font-weight: 600;
            color: var(--text-main);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            min-width: 0;
            flex: 1;
        }

        .card-row-sub {
            font-size: 0.68rem;
            color: var(--text-dim);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .card-row-right {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 2px;
            flex-shrink: 0;
        }

        .card-row-price {
            font-size: 0.84rem;
            font-weight: 700;
            color: #ffffff;
            font-variant-numeric: tabular-nums;
        }

        /* Badges */
        .badge-chg {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.72rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
            line-height: 1.2;
        }

        .badge-up {
            background-color: rgba(14, 203, 129, 0.15);
            color: var(--c-up);
            border: 1px solid rgba(14, 203, 129, 0.25);
        }

        .badge-down {
            background-color: rgba(246, 70, 93, 0.15);
            color: var(--c-down);
            border: 1px solid rgba(246, 70, 93, 0.25);
        }

        .badge-zero {
            background-color: rgba(132, 142, 156, 0.15);
            color: var(--text-sub);
            border: 1px solid rgba(132, 142, 156, 0.25);
        }

        /* Category & Rate Pills Toolbar */
        .overview-toolbar {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 10px 14px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            flex-shrink: 0;
            width: 100%;
            max-width: 100%;
            min-width: 0;
            overflow: hidden;
            box-sizing: border-box;
        }

        .toolbar-row {
            display: flex;
            align-items: center;
            width: 100%;
            max-width: 100%;
            min-width: 0;
            overflow: hidden;
        }

        .pills-group {
            display: flex;
            align-items: center;
            gap: 6px;
            overflow-x: auto;
            overflow-y: hidden;
            -webkit-overflow-scrolling: touch;
            touch-action: pan-x;
            width: 100%;
            max-width: 100%;
            min-width: 0;
            flex-wrap: nowrap;
            padding: 2px 0 4px 0;
            scrollbar-width: none;
            -ms-overflow-style: none;
            cursor: grab;
            user-select: none;
            -webkit-user-select: none;
        }

        .pills-group:active, .pills-group.dragging {
            cursor: grabbing;
        }

        .pills-group::-webkit-scrollbar {
            display: none;
            width: 0;
            height: 0;
        }

        .pill-btn {
            flex-shrink: 0;
            background: transparent;
            color: var(--text-sub);
            border: 1px solid transparent;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 0.84rem;
            font-weight: 600;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.15s ease;
        }

        .pill-btn:hover {
            color: var(--text-main);
            background-color: rgba(255, 255, 255, 0.04);
        }

        .pill-btn.active {
            background-color: #2a2e39;
            color: #ffffff;
            border-color: #3b4252;
        }

        .pill-sm {
            padding: 4px 10px;
            font-size: 0.78rem;
            border-radius: 4px;
        }

        .rate-label {
            font-size: 0.75rem;
            color: var(--text-dim);
            font-weight: 600;
            white-space: nowrap;
            margin-right: 2px;
        }

        /* Search Input */
        .search-box-wrapper {
            position: relative;
            display: flex;
            align-items: center;
            width: 280px;
            max-width: 320px;
            flex-shrink: 0;
        }

        .search-icon {
            position: absolute;
            left: 10px;
            color: var(--text-dim);
            font-size: 0.85rem;
            pointer-events: none;
        }

        .search-input {
            width: 100%;
            background-color: #12141a;
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 7px 32px 7px 30px;
            border-radius: 6px;
            font-size: 0.82rem;
            outline: none;
            transition: border-color 0.15s ease;
        }

        .search-input:focus {
            border-color: var(--accent-blue);
        }

        .search-clear {
            position: absolute;
            right: 8px;
            background: transparent;
            border: none;
            color: var(--text-dim);
            cursor: pointer;
            font-size: 0.85rem;
            padding: 2px 4px;
            display: none;
        }

        .search-clear:hover {
            color: var(--text-main);
        }

        .search-highlight {
            background-color: rgba(240, 185, 11, 0.22);
            color: #f0b90b;
            font-weight: 700;
            padding: 0 1px;
            border-radius: 2px;
        }

        /* Market Table */
        .table-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            overflow: hidden;
            flex-shrink: 0;
        }

        .table-responsive {
            width: 100%;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }

        .market-table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.84rem;
        }

        .market-table thead {
            background-color: #14171f;
            border-bottom: 1px solid var(--border-color);
        }

        .market-table th {
            padding: 11px 16px;
            color: var(--text-sub);
            font-size: 0.72rem;
            font-weight: 600;
            letter-spacing: 0.3px;
            white-space: nowrap;
            user-select: none;
        }

        .market-table th.sortable {
            cursor: pointer;
            transition: color 0.15s ease;
        }

        .market-table th.sortable:hover {
            color: #ffffff;
        }

        .sort-icon {
            font-size: 0.68rem;
            margin-left: 3px;
            opacity: 0.6;
        }

        .sort-icon.active {
            opacity: 1;
            color: var(--accent-blue);
        }

        .market-table tbody tr {
            border-bottom: 1px solid var(--border-subtle);
            cursor: pointer;
            transition: background-color 0.15s ease;
        }

        .market-table tbody tr:hover {
            background-color: var(--bg-card-hover);
        }

        .market-table td {
            padding: 12px 16px;
            white-space: nowrap;
            vertical-align: middle;
        }

        /* Star Button */
        .btn-star {
            background: transparent;
            border: none;
            color: #4a4f5d;
            font-size: 1.1rem;
            cursor: pointer;
            line-height: 1;
            transition: color 0.15s ease, transform 0.15s ease;
            padding: 2px 4px;
        }

        .btn-star:hover {
            color: var(--accent-gold);
            transform: scale(1.15);
        }

        .btn-star.active {
            color: var(--accent-gold);
        }

        /* Item Name & Category Tags */
        .item-name-cell {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .cat-tag {
            font-size: 0.68rem;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 3px;
            letter-spacing: 0.2px;
            white-space: nowrap;
        }

        .cat-acc {
            background-color: rgba(41, 98, 255, 0.15);
            color: #5c9cff;
            border: 1px solid rgba(41, 98, 255, 0.25);
        }

        .cat-wpn {
            background-color: rgba(156, 39, 176, 0.15);
            color: #ce93d8;
            border: 1px solid rgba(156, 39, 176, 0.25);
        }

        .cat-arm {
            background-color: rgba(0, 188, 212, 0.15);
            color: #4dd0e1;
            border: 1px solid rgba(0, 188, 212, 0.25);
        }

        .cat-cash {
            background-color: rgba(240, 185, 11, 0.15);
            color: var(--accent-gold);
            border: 1px solid rgba(240, 185, 11, 0.25);
        }

        .cat-mat {
            background-color: rgba(76, 175, 80, 0.15);
            color: #81c784;
            border: 1px solid rgba(76, 175, 80, 0.25);
        }

        .cat-skill {
            background-color: rgba(255, 87, 34, 0.15);
            color: #ff8a65;
            border: 1px solid rgba(255, 87, 34, 0.25);
        }

        .item-title-text {
            font-weight: 600;
            color: #ffffff;
            font-size: 0.88rem;
        }

        .price-text {
            font-weight: 700;
            font-size: 0.92rem;
            font-variant-numeric: tabular-nums;
            color: #ffffff;
        }

        .turnover-val {
            font-weight: 600;
            color: #ffffff;
            font-variant-numeric: tabular-nums;
        }

        .turnover-sub {
            font-size: 0.7rem;
            color: var(--text-dim);
            margin-top: 1px;
        }

        .ask-val {
            font-weight: 600;
            color: var(--c-ask);
            font-variant-numeric: tabular-nums;
        }

        .ask-spread {
            font-size: 0.72rem;
            margin-top: 1px;
        }

        .range-text {
            font-size: 0.8rem;
            color: var(--text-sub);
            font-variant-numeric: tabular-nums;
        }

        .no-data-msg {
            text-align: center;
            padding: 40px 20px;
            color: var(--text-dim);
            font-size: 0.88rem;
        }

        /* ----------------------------------------------------
           CANDLESTICK CHART VIEW (#view-chart)
           ---------------------------------------------------- */
        #view-chart {
            display: none;
            flex-direction: column;
            align-items: center;
            height: 100%;
            overflow: hidden;
            width: 100%;
        }

        .chart-content {
            width: 100%;
            max-width: 1240px;
            display: flex;
            flex-direction: column;
            height: 100%;
            min-height: 0;
            border-left: 1px solid var(--border-color);
            border-right: 1px solid var(--border-color);
            background-color: var(--bg-main);
        }

        .chart-control-bar {
            background-color: var(--bg-card);
            padding: 8px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            border-bottom: 1px solid var(--border-color);
            flex-shrink: 0;
        }

        .chart-control-left {
            display: flex;
            align-items: center;
            gap: 14px;
            min-width: 0;
        }

        .btn-back-overview {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background-color: #222634;
            color: #ffffff;
            border: 1px solid #333a4c;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 0.82rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.18s ease;
            white-space: nowrap;
            flex-shrink: 0;
        }

        .btn-back-overview:hover {
            background-color: var(--accent-blue);
            border-color: var(--accent-blue);
            box-shadow: 0 2px 10px rgba(41, 98, 255, 0.4);
        }

        .btn-back-overview .arrow-icon {
            font-size: 1rem;
            transition: transform 0.18s ease;
        }

        .btn-back-overview:hover .arrow-icon {
            transform: translateX(-3px);
        }

        .chart-active-item {
            display: flex;
            align-items: center;
            gap: 8px;
            min-width: 0;
        }

        .chart-active-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: #ffffff;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .chart-control-right {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-shrink: 0;
        }

        .tf-group {
            display: inline-flex;
            background-color: #12141a;
            border-radius: 6px;
            padding: 2px;
            border: 1px solid var(--border-color);
        }

        .btn-tf {
            background: transparent;
            color: var(--text-sub);
            border: none;
            padding: 5px 12px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .btn-tf:hover {
            color: var(--text-main);
        }

        .btn-tf.active {
            background-color: var(--accent-blue);
            color: #ffffff;
        }

        .chart-select-box {
            min-width: 180px;
            max-width: 260px;
        }

        select.item-dropdown {
            width: 100%;
            background-color: #222634;
            color: var(--text-main);
            border: 1px solid #333a4c;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.82rem;
            font-weight: 500;
            outline: none;
            cursor: pointer;
            appearance: none;
            background-image: url('data:image/svg+xml;utf8,<svg fill="%23d1d4dc" height="24" viewBox="0 0 24 24" width="24" xmlns="http://www.w3.org/2000/svg"><path d="M7 10l5 5 5-5z"/></svg>');
            background-repeat: no-repeat;
            background-position: right 8px center;
            background-size: 16px;
            padding-right: 28px;
        }

        select.item-dropdown:focus {
            border-color: var(--accent-blue);
        }

        /* Financial Metrics Strip */
        .metric-bar {
            background-color: #141720;
            padding: 8px 16px;
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 12px;
            border-bottom: 1px solid var(--border-color);
            flex-shrink: 0;
        }

        .metric {
            display: flex;
            flex-direction: column;
            gap: 2px;
            min-width: 0;
        }

        .metric-label {
            color: var(--text-sub);
            font-size: 0.68rem;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .metric-val {
            font-weight: 700;
            font-size: 0.94rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            font-variant-numeric: tabular-nums;
        }

        .c-up { color: var(--c-up); }
        .c-down { color: var(--c-down); }
        .c-ask { color: var(--c-ask); }

        #chart-container {
            flex: 1;
            position: relative;
            width: 100%;
            min-height: 0;
            touch-action: pan-y pinch-zoom;
        }

        /* Footer Attribution */
        .app-footer {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 10px 20px;
            padding-bottom: max(10px, env(safe-area-inset-bottom));
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.72rem;
            color: var(--text-sub);
            flex-shrink: 0;
            width: 100%;
            box-sizing: border-box;
        }

        .footer-status {
            display: flex;
            align-items: center;
            gap: 7px;
        }

        .sync-time {
            color: #d1d4dc;
            font-weight: 600;
        }

        .footer-credit strong {
            color: #e5e7eb;
            letter-spacing: 0.3px;
        }

        /* ----------------------------------------------------
           RESPONSIVE MOBILE STYLES (<= 768px)
           ---------------------------------------------------- */
        @media (max-width: 1280px) {
            .overview-content, .header-inner, .chart-content {
                max-width: 100%;
                border-left: none;
                border-right: none;
            }
        }

        @media (max-width: 1024px) {
            .top-cards-grid {
                grid-template-columns: repeat(2, 1fr);
                gap: 12px;
            }
        }

        @media (max-width: 768px) {
            .app-header {
                padding: 8px 12px;
            }

            .brand-logo-img {
                width: 30px;
                height: 30px;
            }

            #view-overview {
                padding: 10px 12px 30px;
            }

            .overview-content {
                gap: 12px;
            }

            .top-cards-grid {
                grid-template-columns: 1fr;
                gap: 10px;
            }

            .overview-toolbar {
                padding: 8px 10px;
            }

            .toolbar-row {
                width: 100%;
                min-width: 0;
            }

            .pills-group {
                width: 100%;
                min-width: 0;
            }

            .search-box-wrapper {
                flex: none;
                width: 140px;
                max-width: 140px;
                transition: width 0.2s ease;
            }

            .search-box-wrapper:focus-within {
                width: 165px;
                max-width: 175px;
            }

            .market-table th, .market-table td {
                padding: 9px 10px;
                font-size: 0.8rem;
            }

            .col-range {
                display: none;
            }

            .chart-control-bar {
                flex-direction: column;
                align-items: stretch;
                padding: 8px 12px;
                gap: 8px;
            }

            .chart-control-left {
                justify-content: space-between;
            }

            .chart-control-right {
                justify-content: space-between;
                width: 100%;
            }

            .chart-select-box {
                flex: 1;
                max-width: 100%;
            }

            .metric-bar {
                grid-template-columns: repeat(3, 1fr);
                gap: 6px 10px;
                padding: 6px 12px;
            }

            .metric-label {
                font-size: 0.65rem;
            }

            .metric-val {
                font-size: 0.86rem;
            }

            .app-footer {
                padding: 6px 12px;
                padding-bottom: max(6px, env(safe-area-inset-bottom));
                font-size: 0.68rem;
            }

            .btn-back-text {
                display: none;
            }

            .btn-back-overview {
                padding: 6px 10px;
            }
        }

        @media (max-width: 420px) {
            .search-box-wrapper {
                width: 125px;
                max-width: 130px;
            }

            .search-box-wrapper:focus-within {
                width: 148px;
                max-width: 155px;
            }

            .search-input {
                padding: 5px 22px 5px 24px;
                font-size: 0.76rem;
            }

            .search-icon {
                left: 7px;
                font-size: 0.75rem;
            }

            .search-clear {
                right: 5px;
                font-size: 0.76rem;
            }

            .col-turnover {
                display: none;
            }
        }
    </style>
</head>
<body>
    <!-- App Universal Header -->
    <header class="app-header">
        <div class="header-inner">
            <div class="brand-box" onclick="showOverview()" title="返回市場總覽">
                <img class="brand-logo-img" src="data:image/png;base64,__ICON_BASE64__" alt="Artale Market" />
                <div class="brand-title">
                    <span>Artale Market</span>
                </div>
            </div>
            <div class="search-box-wrapper">
                <span class="search-icon">🔍</span>
                <input type="text" id="input-search" class="search-input" placeholder="搜尋道具..." autocomplete="off" />
                <button id="btn-clear-search" class="search-clear">✕</button>
            </div>
        </div>
    </header>

    <!-- VIEW 1: BINANCE-STYLE MARKET OVERVIEW -->
    <div id="view-overview" class="view-container">
        <div class="overview-content">
            <!-- Top 4 Summary Cards -->
            <div class="top-cards-grid" id="top-cards-container">
                <!-- Rendered by JS -->
            </div>

        <!-- Filter Toolbar -->
        <div class="overview-toolbar">
            <div class="toolbar-row">
                <div class="pills-group" id="cat-pills">
                    <button class="pill-btn active" data-cat="all">全部 (<span id="count-all">0</span>)</button>
                    <button class="pill-btn" data-cat="fav">⭐ 自選 (<span id="count-fav">0</span>)</button>
                    <button class="pill-btn" data-cat="飾品卷">飾品卷 (<span id="count-acc">0</span>)</button>
                    <button class="pill-btn" data-cat="武器卷">武器卷 (<span id="count-wpn">0</span>)</button>
                    <button class="pill-btn" data-cat="防具卷">防具卷 (<span id="count-arm">0</span>)</button>
                    <button class="pill-btn" data-cat="現金道具">現金道具 (<span id="count-cash">0</span>)</button>
                    <button class="pill-btn" data-cat="材料">材料 (<span id="count-mat">0</span>)</button>
                    <button class="pill-btn" data-cat="技能書">技能書 (<span id="count-skill">0</span>)</button>
                </div>
            </div>
            <div class="toolbar-row" id="rate-row">
                <div class="pills-group">
                    <span class="rate-label">成功率:</span>
                    <button class="pill-btn pill-sm active" data-rate="all">全部</button>
                    <button class="pill-btn pill-sm" data-rate="10%">10%</button>
                    <button class="pill-btn pill-sm" data-rate="30%">30%</button>
                    <button class="pill-btn pill-sm" data-rate="60%">60%</button>
                    <button class="pill-btn pill-sm" data-rate="70%">70%</button>
                    <button class="pill-btn pill-sm" data-rate="100%">100%</button>
                </div>
            </div>
        </div>

        <!-- Market Table -->
        <div class="table-card">
            <div class="table-responsive">
                <table class="market-table">
                    <thead>
                        <tr>
                            <th style="width: 36px; text-align: center;">⭐</th>
                            <th data-sort="name" class="sortable">道具名稱 <span class="sort-icon" id="sort-name">↕</span></th>
                            <th data-sort="price" class="sortable" style="text-align: right;">最新成交價 <span class="sort-icon" id="sort-price">↕</span></th>
                            <th data-sort="chg" class="sortable" style="text-align: right;">24h 漲跌 <span class="sort-icon" id="sort-chg">↕</span></th>
                            <th data-sort="turnover" class="sortable col-turnover" style="text-align: right;">24h 成交額 / 量 <span class="sort-icon active" id="sort-turnover">↓</span></th>
                            <th data-sort="ask" class="sortable" style="text-align: right;">最低掛賣 (價差) <span class="sort-icon" id="sort-ask">↕</span></th>
                            <th class="col-range" style="text-align: right;">24h 價格區間</th>
                        </tr>
                    </thead>
                    <tbody id="market-table-body">
                        <!-- Rendered by JS -->
                    </tbody>
                </table>
            </div>
            <div id="no-matches" class="no-data-msg" style="display: none;">
                查無符合條件的道具
            </div>
        </div>

        <!-- Overview Footer -->
        <footer class="app-footer">
            <div class="footer-status">
                <span class="status-dot"></span>
                <span>Last Updated: <strong class="sync-time">__LAST_SYNCED__</strong></span>
            </div>
            <div class="footer-credit">
                <span>© 2026 By <strong>G8G</strong></span>
            </div>
        </footer>
        </div>
    </div>

    <!-- VIEW 2: TRADINGVIEW CANDLESTICK CHART -->
    <div id="view-chart" class="view-container">
        <div class="chart-content">
            <!-- Sub-Header Chart Controls -->
            <div class="chart-control-bar">
                <div class="chart-control-left">
                    <button class="btn-back-overview" onclick="showOverview()" title="返回市場總覽">
                        <span class="arrow-icon">←</span> <span class="btn-back-text">返回市場總覽</span>
                    </button>
                    <div class="chart-active-item">
                        <span class="cat-tag" id="chart-item-tag">--</span>
                        <span class="chart-active-title" id="chart-item-title">--</span>
                    </div>
                </div>
                <div class="chart-control-right">
                    <div class="tf-group">
                        <button class="btn-tf active" data-tf="1h">1H</button>
                        <button class="btn-tf" data-tf="4h">4H</button>
                        <button class="btn-tf" data-tf="1d">1D</button>
                    </div>
                    <div class="chart-select-box">
                        <select id="item-selector" class="item-dropdown"></select>
                    </div>
                </div>
            </div>

            <!-- Metric Strip -->
            <div class="metric-bar">
                <div class="metric">
                    <span class="metric-label">最新成交</span>
                    <span class="metric-val" id="val-close">--</span>
                </div>
                <div class="metric">
                    <span class="metric-label">最低掛賣</span>
                    <span class="metric-val c-ask" id="val-ask">--</span>
                </div>
                <div class="metric">
                    <span class="metric-label">買賣價差</span>
                    <span class="metric-val" id="val-spread">--</span>
                </div>
                <div class="metric">
                    <span class="metric-label">成交均價 (VWAP)</span>
                    <span class="metric-val" id="val-vwap">--</span>
                </div>
                <div class="metric">
                    <span class="metric-label">24h 成交量</span>
                    <span class="metric-val" id="val-vol">--</span>
                </div>
                <div class="metric">
                    <span class="metric-label">24h 價格區間</span>
                    <span class="metric-val" id="val-range">--</span>
                </div>
            </div>

            <!-- Chart Canvas -->
            <div id="chart-container"></div>

            <!-- Chart Footer -->
            <footer class="app-footer">
                <div class="footer-status">
                    <span class="status-dot"></span>
                    <span>Last Updated: <strong class="sync-time">__LAST_SYNCED__</strong></span>
                </div>
                <div class="footer-credit">
                    <span>© 2026 By <strong>G8G</strong></span>
                </div>
            </footer>
        </div>
    </div>

    <!-- Frontend Application Logic -->
    <script>
        const payload = __PAYLOAD_JSON__;
        const items = payload.items || [];
        const allData = payload.data || {};
        const summaryList = payload.summary || [];
        const topCardsData = payload.top_cards || {};

        let currentItem = items[0] || "";
        let currentTf = "1h";
        let currentCat = "all";
        let currentRate = "all";
        let searchQuery = "";
        let sortCol = "turnover";
        let sortDir = "desc";

        // Favorites stored in localStorage
        let favorites = new Set();
        try {
            const rawFav = localStorage.getItem("artale_favorites");
            if (rawFav) {
                favorites = new Set(JSON.parse(rawFav));
            }
        } catch (e) {
            favorites = new Set();
        }

        function saveFavorites() {
            try {
                localStorage.setItem("artale_favorites", JSON.stringify(Array.from(favorites)));
            } catch (e) {}
            updateFavoriteCounts();
        }

        function toggleFavorite(itemName, ev) {
            if (ev) ev.stopPropagation();
            if (favorites.has(itemName)) {
                favorites.delete(itemName);
            } else {
                favorites.add(itemName);
            }
            saveFavorites();
            renderTable();
        }

        function updateFavoriteCounts() {
            const countFavEl = document.getElementById("count-fav");
            if (countFavEl) countFavEl.textContent = favorites.size;
        }

        // Formatters
        function formatMeso(val) {
            if (val === null || val === undefined || isNaN(val) || val <= 0) return "--";
            if (val >= 100000000) {
                return (val / 100000000).toFixed(2) + " 億";
            } else if (val >= 10000) {
                return (val / 10000).toFixed(0) + " 萬";
            }
            return Number(val).toLocaleString();
        }

        function formatMesoCompact(val) {
            if (!val || isNaN(val) || val <= 0) return "--";
            if (val >= 100000000) {
                return (val / 100000000).toFixed(2) + " 億";
            } else if (val >= 10000) {
                return (val / 10000).toFixed(0) + " 萬";
            }
            return Number(val).toLocaleString();
        }

        function getCatTagClass(cat) {
            switch(cat) {
                case "技能書": return "cat-skill";
                case "飾品卷": return "cat-acc";
                case "武器卷": return "cat-wpn";
                case "防具卷": return "cat-arm";
                case "現金道具": return "cat-cash";
                case "材料": return "cat-mat";
                default: return "cat-acc";
            }
        }

        function getCatShortName(cat) {
            switch(cat) {
                case "技能書": return "技能";
                case "飾品卷": return "飾品";
                case "武器卷": return "武器";
                case "防具卷": return "防具";
                case "現金道具": return "現金";
                case "材料": return "材料";
                default: return cat;
            }
        }

        // Render Top 4 Summary Cards
        function renderTopCards() {
            const container = document.getElementById("top-cards-container");
            if (!container) return;

            const cardsDef = [
                {
                    title: "🔥 熱門成交",
                    tag: "24h 交易頻次",
                    items: topCardsData.hot || [],
                    renderRight: (it) => `
                        <span class="card-row-price">${formatMesoCompact(it.latest_price)}</span>
                        <span class="badge-chg ${it.chg_24 > 0 ? 'badge-up' : (it.chg_24 < 0 ? 'badge-down' : 'badge-zero')}">
                            ${it.chg_24 > 0 ? '+' : ''}${it.chg_24.toFixed(2)}%
                        </span>`,
                    renderSub: (it) => `${it.trades_24} 筆成交`
                },
                {
                    title: "🚀 24h 漲幅榜",
                    tag: "價格飆升",
                    items: topCardsData.gainers || [],
                    renderRight: (it) => `
                        <span class="card-row-price">${formatMesoCompact(it.latest_price)}</span>
                        <span class="badge-chg badge-up">+${it.chg_24.toFixed(2)}%</span>`,
                    renderSub: (it) => `成交額 ${formatMesoCompact(it.turnover_24)}`
                },
                {
                    title: "💎 24h 成交額榜",
                    tag: "資金流向",
                    items: topCardsData.turnover || [],
                    renderRight: (it) => `
                        <span class="card-row-price">${formatMesoCompact(it.turnover_24)}</span>
                        <span class="badge-chg ${it.chg_24 > 0 ? 'badge-up' : (it.chg_24 < 0 ? 'badge-down' : 'badge-zero')}">
                            ${it.chg_24 > 0 ? '+' : ''}${it.chg_24.toFixed(2)}%
                        </span>`,
                    renderSub: (it) => `單價 ${formatMesoCompact(it.latest_price)}`
                },
                {
                    title: "⚡ 最低掛牌溢價",
                    tag: "買賣價差優選",
                    items: topCardsData.spreads || [],
                    renderRight: (it) => `
                        <span class="card-row-price c-ask">${formatMesoCompact(it.lowest_ask)}</span>
                        <span class="badge-chg ${it.spread_pct <= 0 ? 'badge-up' : 'badge-down'}">
                            ${it.spread_pct > 0 ? '+' : ''}${it.spread_pct.toFixed(1)}%
                        </span>`,
                    renderSub: (it) => `成交價 ${formatMesoCompact(it.latest_price)}`
                }
            ];

            let html = "";
            cardsDef.forEach(c => {
                html += `
                <div class="summary-card">
                    <div class="card-head">
                        <span class="card-title">${c.title}</span>
                        <span class="card-tag">${c.tag}</span>
                    </div>
                    <div class="card-list">
                `;
                c.items.forEach(it => {
                    html += `
                        <div class="card-row" onclick="showChart('${it.name}')">
                            <div class="card-row-left">
                                <div class="card-row-title-box">
                                    <span class="cat-tag ${getCatTagClass(it.category)}">${getCatShortName(it.category)}</span>
                                    <span class="card-row-name" title="${it.name}">${it.name}</span>
                                </div>
                                <div class="card-row-sub">${c.renderSub(it)}</div>
                            </div>
                            <div class="card-row-right">
                                ${c.renderRight(it)}
                            </div>
                        </div>
                    `;
                });
                html += `</div></div>`;
            });

            container.innerHTML = html;
        }

        // ----------------------------------------------------
        // Smart Search Engine (Multi-Token, Boundary, Subsequence & Highlight)
        // ----------------------------------------------------
        function tokenizeSearchQuery(query) {
            if (!query) return [];
            // Normalize full-width characters (e.g. ３０ -> 30) and lowercase
            let q = query.trim().toLowerCase()
                .replace(/[\uff01-\uff5e]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0xfee0));

            // Insert boundary spaces between Hanzi and Alphanumeric / Digits (e.g. 腰帶30 -> 腰帶 30)
            q = q.replace(/([\u4e00-\u9fa5])([0-9a-zA-Z])/g, '$1 $2')
                 .replace(/([0-9a-zA-Z%])([\u4e00-\u9fa5])/g, '$1 $2');

            // Split by whitespace and normalize trailing '%'
            return q.split(/\\s+/)
                    .filter(t => t.length > 0)
                    .map(t => (t.length > 1 && t.endsWith('%')) ? t.slice(0, -1) : t);
        }

        function mergeIntervals(intervals) {
            if (!intervals || intervals.length === 0) return [];
            intervals.sort((a, b) => a[0] - b[0]);
            const merged = [intervals[0].slice()];
            for (let i = 1; i < intervals.length; i++) {
                const last = merged[merged.length - 1];
                const curr = intervals[i];
                if (curr[0] <= last[1]) {
                    last[1] = Math.max(last[1], curr[1]);
                } else {
                    merged.push(curr.slice());
                }
            }
            return merged;
        }

        function highlightMatchedText(rawText, intervals) {
            if (!intervals || intervals.length === 0) return rawText;
            const merged = mergeIntervals(intervals);
            let out = "";
            let cursor = 0;
            for (const [start, end] of merged) {
                out += rawText.slice(cursor, start);
                out += '<mark class="search-highlight">' + rawText.slice(start, end) + '</mark>';
                cursor = end;
            }
            out += rawText.slice(cursor);
            return out;
        }

        function smartMatch(query, rawName) {
            if (!query) return { matched: true, intervals: [] };
            const qClean = query.trim().toLowerCase();
            const nameLower = rawName.toLowerCase();

            // Tier 1: Direct Substring Match
            const exactIdx = nameLower.indexOf(qClean);
            if (exactIdx !== -1) {
                return {
                    matched: true,
                    intervals: [[exactIdx, exactIdx + qClean.length]]
                };
            }

            // Tier 2: Token Conjunction (AND Logic with script-boundary splitting)
            const tokens = tokenizeSearchQuery(query);
            if (tokens.length > 0) {
                let allTokensMatch = true;
                const tokenIntervals = [];

                for (const token of tokens) {
                    const idx = nameLower.indexOf(token);
                    if (idx === -1) {
                        allTokensMatch = false;
                        break;
                    }
                    // Collect all occurrences of this token for highlighting
                    let startPos = 0;
                    while ((startPos = nameLower.indexOf(token, startPos)) !== -1) {
                        tokenIntervals.push([startPos, startPos + token.length]);
                        startPos += token.length;
                    }
                }

                if (allTokensMatch) {
                    return {
                        matched: true,
                        intervals: tokenIntervals
                    };
                }
            }

            // Tier 3: Subsequence Match (Fuzzy Shorthand, e.g. 腰力30 -> 腰帶力量卷軸30%)
            const pSeq = qClean.replace(/\\s+/g, "");
            if (pSeq.length >= 2) {
                let pIdx = 0;
                const seqIntervals = [];
                for (let sIdx = 0; sIdx < nameLower.length && pIdx < pSeq.length; sIdx++) {
                    if (nameLower[sIdx] === pSeq[pIdx]) {
                        seqIntervals.push([sIdx, sIdx + 1]);
                        pIdx++;
                    }
                }
                if (pIdx === pSeq.length) {
                    return {
                        matched: true,
                        intervals: seqIntervals
                    };
                }
            }

            return { matched: false, intervals: [] };
        }

        // Render Market Table
        function renderTable() {
            const tbody = document.getElementById("market-table-body");
            const noMatches = document.getElementById("no-matches");
            if (!tbody) return;

            let filtered = summaryList.filter(it => {
                // Category
                if (currentCat === "fav") {
                    if (!favorites.has(it.name)) return false;
                } else if (currentCat !== "all") {
                    if (it.category !== currentCat) return false;
                }

                // Rate
                if (currentCat !== "現金道具" && currentCat !== "材料" && currentCat !== "技能書" && currentRate !== "all") {
                    if (it.rate !== currentRate) return false;
                }

                // Search query with smart matching
                if (searchQuery) {
                    const res = smartMatch(searchQuery, it.name);
                    if (!res.matched) return false;
                    it._highlightIntervals = res.intervals;
                } else {
                    it._highlightIntervals = null;
                }

                return true;
            });

            // Sorting
            filtered.sort((a, b) => {
                let vA, vB;
                if (sortCol === "name") {
                    vA = a.name;
                    vB = b.name;
                    return sortDir === "asc" ? vA.localeCompare(vB, "zh-Hant") : vB.localeCompare(vA, "zh-Hant");
                } else if (sortCol === "price") {
                    vA = a.latest_price || 0;
                    vB = b.latest_price || 0;
                } else if (sortCol === "chg") {
                    vA = a.chg_24 || -9999;
                    vB = b.chg_24 || -9999;
                } else if (sortCol === "turnover") {
                    vA = a.turnover_24 || 0;
                    vB = b.turnover_24 || 0;
                } else if (sortCol === "ask") {
                    vA = a.lowest_ask || (sortDir === "asc" ? 999999999999 : -1);
                    vB = b.lowest_ask || (sortDir === "asc" ? 999999999999 : -1);
                }
                return sortDir === "asc" ? (vA - vB) : (vB - vA);
            });

            if (filtered.length === 0) {
                tbody.innerHTML = "";
                noMatches.style.display = "block";
                return;
            }
            noMatches.style.display = "none";

            let html = "";
            filtered.forEach(it => {
                const isFav = favorites.has(it.name);
                const chgClass = it.chg_24 > 0 ? "badge-up" : (it.chg_24 < 0 ? "badge-down" : "badge-zero");
                const chgSign = it.chg_24 > 0 ? "+" : "";
                const spreadText = it.spread_pct !== null ? `${it.spread_pct > 0 ? '+' : ''}${it.spread_pct.toFixed(1)}%` : "--";
                const spreadClass = it.spread_pct !== null ? (it.spread_pct <= 0 ? "c-up" : "c-down") : "text-dim";
                const rangeStr = (it.low_24 > 0 && it.high_24 > 0) ? `${formatMesoCompact(it.low_24)} ~ ${formatMesoCompact(it.high_24)}` : "--";
                const titleHtml = (searchQuery && it._highlightIntervals)
                    ? highlightMatchedText(it.name, it._highlightIntervals)
                    : it.name;

                html += `
                <tr onclick="showChart('${it.name}')">
                    <td style="text-align: center;" onclick="event.stopPropagation()">
                        <button class="btn-star ${isFav ? 'active' : ''}" onclick="toggleFavorite('${it.name}', event)" title="${isFav ? '取消自選' : '加入自選'}">
                            ${isFav ? '★' : '☆'}
                        </button>
                    </td>
                    <td>
                        <div class="item-name-cell">
                            <span class="cat-tag ${getCatTagClass(it.category)}">${getCatShortName(it.category)}</span>
                            <span class="item-title-text">${titleHtml}</span>
                        </div>
                    </td>
                    <td style="text-align: right;">
                        <div class="price-text">${formatMeso(it.latest_price)}</div>
                    </td>
                    <td style="text-align: right;">
                        <span class="badge-chg ${chgClass}">${chgSign}${it.chg_24.toFixed(2)}%</span>
                    </td>
                    <td style="text-align: right;" class="col-turnover">
                        <div class="turnover-val">${formatMeso(it.turnover_24)}</div>
                        <div class="turnover-sub">${it.vol_24.toLocaleString()} 件 (${it.trades_24} 筆)</div>
                    </td>
                    <td style="text-align: right;">
                        <div class="ask-val">${formatMeso(it.lowest_ask)}</div>
                        <div class="ask-spread ${spreadClass}">價差: ${spreadText}</div>
                    </td>
                    <td style="text-align: right;" class="col-range">
                        <div class="range-text">${rangeStr}</div>
                    </td>
                </tr>
                `;
            });

            tbody.innerHTML = html;
        }

        // Initialize Category Counts
        function initCategoryCounts() {
            document.getElementById("count-all").textContent = summaryList.length;
            document.getElementById("count-acc").textContent = summaryList.filter(s => s.category === "飾品卷").length;
            document.getElementById("count-wpn").textContent = summaryList.filter(s => s.category === "武器卷").length;
            document.getElementById("count-arm").textContent = summaryList.filter(s => s.category === "防具卷").length;
            document.getElementById("count-cash").textContent = summaryList.filter(s => s.category === "現金道具").length;
            document.getElementById("count-mat").textContent = summaryList.filter(s => s.category === "材料").length;
            document.getElementById("count-skill").textContent = summaryList.filter(s => s.category === "技能書").length;
            updateFavoriteCounts();
        }

        // ----------------------------------------------------
        // SPA View Switcher
        // ----------------------------------------------------
        function showOverview() {
            document.getElementById("view-overview").style.display = "flex";
            document.getElementById("view-chart").style.display = "none";
            window.location.hash = "#overview";
        }

        function showChart(itemName) {
            if (itemName && allData[itemName]) {
                currentItem = itemName;
                const sel = document.getElementById("item-selector");
                if (sel) sel.value = itemName;
            }

            document.getElementById("view-overview").style.display = "none";
            document.getElementById("view-chart").style.display = "flex";
            window.location.hash = "#chart?item=" + encodeURIComponent(currentItem);

            // Update item info badge in chart header
            const itObj = summaryList.find(s => s.name === currentItem);
            const titleEl = document.getElementById("chart-item-title");
            const tagEl = document.getElementById("chart-item-tag");
            if (itObj) {
                if (titleEl) titleEl.textContent = itObj.name;
                if (tagEl) {
                    tagEl.textContent = itObj.category;
                    tagEl.className = "cat-tag " + getCatTagClass(itObj.category);
                }
            } else {
                if (titleEl) titleEl.textContent = currentItem;
                if (tagEl) tagEl.textContent = "";
            }

            // Resize and update chart
            setTimeout(() => {
                const rect = chartContainer.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    chart.applyOptions({ width: Math.floor(rect.width), height: Math.floor(rect.height) });
                }
                updateChart();
            }, 30);
        }

        // ----------------------------------------------------
        // Candlestick Chart Engine (Lightweight Charts)
        // ----------------------------------------------------
        const selector = document.getElementById("item-selector");
        const chartContainer = document.getElementById("chart-container");
        const valClose = document.getElementById("val-close");
        const valAsk = document.getElementById("val-ask");
        const valSpread = document.getElementById("val-spread");
        const valVwap = document.getElementById("val-vwap");
        const valVol = document.getElementById("val-vol");
        const valRange = document.getElementById("val-range");

        // Populate item selector
        items.forEach(it => {
            const opt = document.createElement("option");
            opt.value = it;
            opt.textContent = it;
            selector.appendChild(opt);
        });

        const isMobile = window.innerWidth <= 768;

        const chart = LightweightCharts.createChart(chartContainer, {
            layout: {
                fontFamily: "'Google Sans', 'Google Sans Text', 'Noto Sans TC', sans-serif",
                background: { color: '#0b0e14' },
                textColor: '#d1d4dc',
                fontSize: isMobile ? 11 : 12,
            },
            grid: {
                vertLines: { color: '#181c26' },
                horzLines: { color: '#181c26' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
            rightPriceScale: {
                borderColor: '#262b36',
                autoScale: true,
                scaleMargins: {
                    top: 0.08,
                    bottom: 0.20,
                },
                entireTextOnly: false,
            },
            timeScale: {
                borderColor: '#262b36',
                timeVisible: true,
                secondsVisible: false,
                barSpacing: isMobile ? 13 : 18,
                minBarSpacing: 3,
                rightOffset: 3,
            },
            handleScroll: true,
            handleScale: true,
        });

        const candleSeries = chart.addCandlestickSeries({
            upColor: '#0ecb81',
            downColor: '#f6465d',
            borderVisible: false,
            wickUpColor: '#0ecb81',
            wickDownColor: '#f6465d',
            priceFormat: {
                type: 'custom',
                formatter: (price) => {
                    if (price <= 0) return '0';
                    if (price >= 100000000) {
                        return (price / 100000000).toFixed(2) + ' 億';
                    } else if (price >= 10000) {
                        return (price / 10000).toFixed(0) + ' 萬';
                    }
                    return price.toLocaleString();
                }
            },
            autoscaleInfoProvider: (original) => {
                const res = original();
                if (res !== null && res.priceRange) {
                    const minP = res.priceRange.minValue;
                    const maxP = res.priceRange.maxValue;
                    const diff = maxP - minP;
                    const span = diff > 0 ? diff : (maxP > 0 ? maxP * 0.05 : 1000);
                    const pad = span * 0.25;
                    return {
                        priceRange: {
                            minValue: Math.max(1, minP - pad),
                            maxValue: maxP + pad,
                        },
                    };
                }
                return res;
            },
        });

        const volumeSeries = chart.addHistogramSeries({
            color: '#0ecb81',
            priceFormat: { type: 'volume' },
            priceScaleId: '',
        });

        volumeSeries.priceScale().applyOptions({
            scaleMargins: {
                top: 0.8,
                bottom: 0,
            },
        });

        const resizeObserver = new ResizeObserver(entries => {
            if (!entries || entries.length === 0) return;
            const { width, height } = entries[0].contentRect;
            if (width > 0 && height > 0) {
                chart.applyOptions({ width: Math.floor(width), height: Math.floor(height) });
            }
        });
        resizeObserver.observe(chartContainer);

        function updateChart() {
            if (!currentItem || !allData[currentItem]) return;
            const itemObj = allData[currentItem];
            const candles = itemObj[currentTf] || [];
            const lowestAsk = itemObj.lowest_ask;

            const cData = candles.map(c => ({
                time: c.time,
                open: c.open,
                high: c.high,
                low: c.low,
                close: c.close,
            }));

            const vData = candles.map(c => ({
                time: c.time,
                value: c.volume,
                color: c.close >= c.open ? 'rgba(14, 203, 129, 0.45)' : 'rgba(246, 70, 93, 0.45)'
            }));

            cData.sort((a, b) => (a.time > b.time ? 1 : (a.time < b.time ? -1 : 0)));
            vData.sort((a, b) => (a.time > b.time ? 1 : (a.time < b.time ? -1 : 0)));

            candleSeries.setData(cData);
            volumeSeries.setData(vData);

            chart.priceScale('right').applyOptions({ autoScale: true });

            if (candles.length > 0) {
                const latest = candles[candles.length - 1];
                valClose.textContent = formatMeso(latest.close);
                valClose.className = "metric-val " + (latest.close >= latest.open ? "c-up" : "c-down");
                valVwap.textContent = formatMeso(latest.vwap);
                valVol.textContent = latest.volume.toLocaleString() + " 件";

                const allHighs = candles.map(c => c.high);
                const allLows = candles.map(c => c.low);
                const maxH = Math.max(...allHighs);
                const minL = Math.min(...allLows);
                valRange.textContent = formatMeso(maxH) + " / " + formatMeso(minL);

                if (lowestAsk) {
                    valAsk.textContent = formatMeso(lowestAsk);
                    const spread = ((lowestAsk - latest.close) / latest.close) * 100;
                    valSpread.textContent = (spread >= 0 ? "+" : "") + spread.toFixed(1) + "%";
                    valSpread.className = "metric-val " + (spread <= 0 ? "c-up" : "c-down");
                } else {
                    valAsk.textContent = "無掛賣";
                    valSpread.textContent = "N/A";
                    valSpread.className = "metric-val";
                }
            } else {
                valClose.textContent = "無成交數據";
                valClose.className = "metric-val";
                valVwap.textContent = "--";
                valVol.textContent = "--";
                valRange.textContent = "--";
                valAsk.textContent = lowestAsk ? formatMeso(lowestAsk) : "--";
                valSpread.textContent = "--";
                valSpread.className = "metric-val";
            }

            chart.timeScale().fitContent();
        }

        // Crosshair move listener
        chart.subscribeCrosshairMove((param) => {
            if (!param || !param.time || !param.seriesData) return;
            const cItem = param.seriesData.get(candleSeries);
            const vItem = param.seriesData.get(volumeSeries);
            if (cItem) {
                valClose.textContent = formatMeso(cItem.close);
                valClose.className = "metric-val " + (cItem.close >= cItem.open ? "c-up" : "c-down");
                valRange.textContent = formatMeso(cItem.high) + " / " + formatMeso(cItem.low);
            }
            if (vItem) {
                valVol.textContent = vItem.value.toLocaleString() + " 件";
            }
        });

        // ----------------------------------------------------
        // Event Listeners & Setup
        // ----------------------------------------------------
        // Timeframe selector
        document.querySelectorAll(".btn-tf").forEach(btn => {
            btn.addEventListener("click", () => {
                document.querySelectorAll(".btn-tf").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                currentTf = btn.getAttribute("data-tf");
                updateChart();
            });
        });

        // Dropdown selector in chart view
        selector.addEventListener("change", (e) => {
            showChart(e.target.value);
        });

        // Category Pills
        document.querySelectorAll("#cat-pills .pill-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                document.querySelectorAll("#cat-pills .pill-btn").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                currentCat = btn.getAttribute("data-cat");

                const rateRow = document.getElementById("rate-row");
                if (currentCat === "現金道具" || currentCat === "材料" || currentCat === "技能書") {
                    rateRow.style.display = "none";
                    currentRate = "all";
                } else {
                    rateRow.style.display = "flex";
                }
                renderTable();
            });
        });

        // Rate Pills
        document.querySelectorAll("#rate-row .pill-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                document.querySelectorAll("#rate-row .pill-btn").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                currentRate = btn.getAttribute("data-rate");
                renderTable();
            });
        });

        // Search Input
        const searchInput = document.getElementById("input-search");
        const clearBtn = document.getElementById("btn-clear-search");
        searchInput.addEventListener("input", (e) => {
            searchQuery = e.target.value.trim().toLowerCase();
            clearBtn.style.display = searchQuery ? "block" : "none";
            if (document.getElementById("view-chart").style.display === "flex" && searchQuery) {
                showOverview();
            }
            renderTable();
        });

        clearBtn.addEventListener("click", () => {
            searchInput.value = "";
            searchQuery = "";
            clearBtn.style.display = "none";
            renderTable();
        });

        // Table Sorting Header Clicks
        document.querySelectorAll(".market-table th.sortable").forEach(th => {
            th.addEventListener("click", () => {
                const col = th.getAttribute("data-sort");
                if (sortCol === col) {
                    sortDir = sortDir === "desc" ? "asc" : "desc";
                } else {
                    sortCol = col;
                    sortDir = (col === "name") ? "asc" : "desc";
                }

                // Update sort icons
                document.querySelectorAll(".sort-icon").forEach(icon => {
                    icon.className = "sort-icon";
                    icon.textContent = "↕";
                });
                const curIcon = document.getElementById("sort-" + col);
                if (curIcon) {
                    curIcon.className = "sort-icon active";
                    curIcon.textContent = sortDir === "desc" ? "↓" : "↑";
                }

                renderTable();
            });
        });

        // Hash Routing & Browser Back/Forward
        function handleHashRoute() {
            const hash = window.location.hash;
            if (hash.startsWith("#chart")) {
                const params = new URLSearchParams(hash.slice(hash.indexOf("?") + 1));
                const it = params.get("item");
                if (it && allData[it]) {
                    showChart(it);
                    return;
                }
                showChart(currentItem);
            } else {
                showOverview();
            }
        }

        window.addEventListener("hashchange", handleHashRoute);

        // Draggable Pills Functionality (Touch & Mouse Drag)
        function initDraggablePills() {
            document.querySelectorAll(".pills-group").forEach(slider => {
                let isDown = false;
                let startX = 0;
                let scrollLeft = 0;
                let hasMoved = false;

                // Mouse Drag
                slider.addEventListener("mousedown", (e) => {
                    isDown = true;
                    hasMoved = false;
                    slider.classList.add("dragging");
                    startX = e.pageX - slider.offsetLeft;
                    scrollLeft = slider.scrollLeft;
                });

                window.addEventListener("mouseup", () => {
                    if (isDown) {
                        isDown = false;
                        slider.classList.remove("dragging");
                    }
                });

                slider.addEventListener("mouseleave", () => {
                    if (isDown) {
                        isDown = false;
                        slider.classList.remove("dragging");
                    }
                });

                slider.addEventListener("mousemove", (e) => {
                    if (!isDown) return;
                    e.preventDefault();
                    const x = e.pageX - slider.offsetLeft;
                    const walk = (x - startX) * 1.5;
                    if (Math.abs(walk) > 4) {
                        hasMoved = true;
                    }
                    slider.scrollLeft = scrollLeft - walk;
                });

                // Prevent button click if dragging
                slider.querySelectorAll(".pill-btn").forEach(btn => {
                    btn.addEventListener("click", (e) => {
                        if (hasMoved) {
                            e.preventDefault();
                            e.stopPropagation();
                            hasMoved = false;
                        }
                    }, true);
                });

                // Touch Drag (guarantees fluid dragging across mobile webviews)
                let touchStartX = 0;
                let touchScrollLeft = 0;
                slider.addEventListener("touchstart", (e) => {
                    touchStartX = e.touches[0].pageX;
                    touchScrollLeft = slider.scrollLeft;
                }, { passive: true });

                slider.addEventListener("touchmove", (e) => {
                    const touchX = e.touches[0].pageX;
                    const moveDiff = touchStartX - touchX;
                    slider.scrollLeft = touchScrollLeft + moveDiff;
                }, { passive: true });
            });
        }

        // Initial Initialization
        initCategoryCounts();
        renderTopCards();
        renderTable();
        initDraggablePills();

        if (window.location.hash.startsWith("#chart")) {
            handleHashRoute();
        } else {
            showOverview();
        }
    </script>
</body>
</html>
"""
    # Replace tokens
    icon_file = Path(__file__).resolve().parent / "assets" / "icon_base64.txt"
    icon_b64 = icon_file.read_text(encoding="utf-8").strip() if icon_file.exists() else ""

    final_html = template.replace("/*__LIGHTWEIGHT_CHARTS_JS__*/", js_code)
    final_html = final_html.replace("__PAYLOAD_JSON__", json_str)
    final_html = final_html.replace("__LAST_SYNCED__", last_synced_time)
    final_html = final_html.replace("__ICON_BASE64__", icon_b64)

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(final_html)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    with open(DOCS_HTML, "w", encoding="utf-8") as f:
        f.write(final_html)

    print(f"Generated Binance-Style Overview & Chart Dashboard:")
    print(f"  Local: {OUTPUT_HTML}")
    print(f"  Docs:  {DOCS_HTML}")
    return OUTPUT_HTML

if __name__ == "__main__":
    out = generate_dashboard_html()
