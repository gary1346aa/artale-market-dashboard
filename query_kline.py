import sqlite3
import sys
import io
import argparse
from pathlib import Path

# Ensure UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DB_PATH = Path(__file__).resolve().parent / "data" / "market.db"

def print_item_kline(item_name: str, timeframe: str = "1d"):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT bucket_time, open_price, high_price, low_price, close_price, volume, vwap, lowest_ask
            FROM kline_candles
            WHERE item_name LIKE ? AND timeframe = ?
            ORDER BY bucket_time ASC
        """, (f"%{item_name}%", timeframe))
        rows = c.fetchall()

        if not rows:
            print(f"No candlestick data found for '{item_name}' ({timeframe}).")
            return

        c.execute("SELECT DISTINCT item_name FROM kline_candles WHERE item_name LIKE ?", (f"%{item_name}%",))
        actual_name = c.fetchone()[0]

        print("=" * 88)
        print(f"  Artale K-Line Terminal: {actual_name} [{timeframe.upper()}]")
        print("=" * 88)
        print(f"{'Date / Time':<19} | {'Open':>11} | {'High':>11} | {'Low':>11} | {'Close':>11} | {'Vol':>4} | {'VWAP':>11}")
        print("-" * 88)

        lowest_ask = None
        for r in rows:
            t_str = r[0] if timeframe != "1d" else r[0][:10]
            o, h, l, cl, vol, vwap, ask = r[1], r[2], r[3], r[4], r[5], r[6], r[7]
            if ask: lowest_ask = ask
            
            # Trend marker
            marker = "▲" if cl >= o else "▼"
            print(f"{t_str:<19} | {o:>11,} | {h:>11,} | {l:>11,} | {cl:>10,}{marker} | {vol:>4} | {vwap:>11,}")

        print("-" * 88)
        if lowest_ask and rows:
            last_close = rows[-1][4]
            spread = ((lowest_ask - last_close) / last_close) * 100
            print(f"  [Current Lowest Ask]: {lowest_ask:>12,} Meso")
            print(f"  [Latest Traded Price]: {last_close:>11,} Meso")
            print(f"  [Spread (Ask Markup)]: {spread:>+11.1f}%")
        print("=" * 88)

def main():
    parser = argparse.ArgumentParser(description="Query K-Line Candlesticks directly in terminal")
    parser.add_argument("item", nargs="?", default="墜飾敏捷卷軸30%", help="Item name to query (default: 墜飾敏捷卷軸30%%)")
    parser.add_argument("--tf", choices=["1h", "4h", "1d"], default="1d", help="Candlestick timeframe (default: 1d)")
    args = parser.parse_args()

    print_item_kline(args.item, args.tf)

if __name__ == "__main__":
    main()
