import sys
import sqlite3
import argparse
from pathlib import Path

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).parent / "data" / "market.db"

def format_meso(val: int) -> str:
    if val >= 100_000_000:
        yi = val // 100_000_000
        rem = val % 100_000_000
        wan = rem // 10_000
        return f"{val:,} ({yi}億{wan}萬)" if wan else f"{val:,} ({yi}億)"
    elif val >= 10_000:
        wan = val // 10_000
        rem = val % 10_000
        return f"{val:,} ({wan}萬{rem:,})" if rem else f"{val:,} ({wan}萬)"
    return f"{val:,}"

def show_category_matrix():
    if not DB_PATH.exists():
        print(f"Error: Database file not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    categories = [
        ("墜飾 (Pendant Scrolls)", "%墜飾%卷軸%"),
        ("眼部裝飾 (Eye Accessory Scrolls)", "%眼部%卷軸%"),
        ("臉部裝飾 (Face Accessory Scrolls)", "%臉部%卷軸%"),
        ("頭盔 (Helmet Scrolls)", "%頭盔%卷軸%")
    ]

    print("=" * 86)
    print("  ARTALE MARKET OVERVIEW: TARGET SCROLLS MATRIX")
    print("=" * 86)

    for cat_title, cat_pattern in categories:
        print(f"\n--- {cat_title} ---")
        c.execute("""
            SELECT item_name, MIN(unit_price) as min_ask, COUNT(*) as active_count
            FROM active_listings
            WHERE item_name LIKE ?
            GROUP BY item_name
            ORDER BY min_ask ASC
        """, (cat_pattern,))
        active_data = {r[0]: (r[1], r[2]) for r in c.fetchall()}

        c.execute("""
            SELECT item_name, matched_unit_price, trade_time
            FROM matched_trades
            WHERE item_name LIKE ?
            ORDER BY trade_time DESC
        """, (cat_pattern,))
        trade_data = {}
        for r in c.fetchall():
            if r[0] not in trade_data:
                trade_data[r[0]] = (r[1], r[2])

        all_items = sorted(set(list(active_data.keys()) + list(trade_data.keys())))
        if not all_items:
            print("  (No tracked items in database yet for this category)")
            continue

        print(f"  {'Item Name':<22}  {'Lowest Ask (查詢)':>20}  {'Latest Trade (市價)':>20}  {'Spread':>14}")
        print("  " + "-" * 82)
        for item in all_items:
            ask_val, ask_cnt = active_data.get(item, (None, 0))
            trade_val, trade_tm = trade_data.get(item, (None, ""))

            ask_str = format_meso(ask_val) if ask_val else "No asks"
            trade_str = format_meso(trade_val) if trade_val else "No trades"

            spread_str = "-"
            if ask_val and trade_val:
                diff = ask_val - trade_val
                pct = (diff / trade_val) * 100
                spread_str = f"{pct:+.1f}%"

            print(f"  {item:<22}  {ask_str:>20}  {trade_str:>20}  {spread_str:>14}")

    print("\n" + "=" * 86)
    conn.close()

def query_market(keyword: str = ""):
    if not keyword:
        show_category_matrix()
        return

    if not DB_PATH.exists():
        print(f"Error: Database file not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    query_filter = f"%{keyword}%"

    print("=" * 78)
    print(f"  ARTALE MARKET REPORT: '{keyword}'")
    print("=" * 78)

    # 1. Active Listings (查詢)
    c.execute("""
        SELECT item_name, quantity, unit_price, total_price, remaining_time, captured_at
        FROM active_listings
        WHERE item_name LIKE ?
        ORDER BY unit_price ASC
        LIMIT 10
    """, (query_filter,))
    active_rows = c.fetchall()

    print("\n[查詢] Active Sell Listings (Lowest Price First):")
    print("-" * 78)
    if not active_rows:
        print("  No active listings found.")
    else:
        print(f"  {'Item Name':<22} {'Qty':>4}  {'Unit Price':>22}  {'Total Price':>20}")
        print("  " + "-" * 74)
        for r in active_rows:
            name, qty, unit, total, remaining, cap_at = r
            print(f"  {name:<22} {qty:>4}  {format_meso(unit):>22}  {format_meso(total):>20}")

    # 2. Matched Trades (市價)
    c.execute("""
        SELECT item_name, quantity, matched_unit_price, total_matched_price, trade_time
        FROM matched_trades
        WHERE item_name LIKE ?
        ORDER BY trade_time DESC, matched_unit_price ASC
        LIMIT 10
    """, (query_filter,))
    trade_rows = c.fetchall()

    print("\n[市價] Completed Trade History (Most Recent First):")
    print("-" * 78)
    if not trade_rows:
        print("  No completed trades found.")
    else:
        print(f"  {'Item Name':<22} {'Qty':>4}  {'Matched Unit':>22}  {'Trade Time':>18}")
        print("  " + "-" * 74)
        for r in trade_rows:
            name, qty, unit, total, t_time = r
            print(f"  {name:<22} {qty:>4}  {format_meso(unit):>22}  {t_time:>18}")

    # 3. Market Spread & Analytics
    if active_rows and trade_rows:
        lowest_ask = active_rows[0][2]
        latest_trade = trade_rows[0][2]
        spread = lowest_ask - latest_trade
        spread_pct = (spread / latest_trade) * 100 if latest_trade else 0.0

        print("\n[Spread & Arbitrage Signals]")
        print("-" * 78)
        print(f"  Lowest Ask Price (查詢):   {format_meso(lowest_ask)} meso")
        print(f"  Latest Trade Price (市價): {format_meso(latest_trade)} meso")
        if spread_pct > 0:
            print(f"  Spread:                    +{spread:,} meso (+{spread_pct:.1f}% Premium over latest trade)")
        elif spread_pct < 0:
            print(f"  Spread:                    {spread:,} meso ({spread_pct:.1f}% Undervalued / Snipe Opportunity!)")
        else:
            print(f"  Spread:                    0 meso (At Market Equilibrium)")

    print("=" * 78)
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query Artale market data & price analytics")
    parser.add_argument("keyword", nargs="?", default="", help="Item name or keyword to query (e.g. '墜飾')")
    args = parser.parse_args()
    query_market(args.keyword)
