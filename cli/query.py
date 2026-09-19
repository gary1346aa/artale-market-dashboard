"""CLI query utility for inspecting trades, candles, and watchlist tiers."""

import argparse
import sys
from typing import Optional

from config.settings import setup_logging
from core.watchlist import WatchlistManager
from storage.database import (
    fetch_active_listings,
    fetch_candles,
    fetch_distinct_items,
    fetch_recent_trades,
)
from visualization.theme import format_price_cjk


def handle_kline(args: argparse.Namespace) -> None:
    """Handles 'kline' subcommand."""
    candles = fetch_candles(
        args.item, timeframe=args.timeframe, limit=args.limit
    )
    if not candles:
        print(f"No {args.timeframe} candles found for '{args.item}'.")
        return

    print(f"\n=== Candlesticks for '{args.item}' ({args.timeframe}) ===")
    header = f"{'Time':<20} | {'Open':>12} | {'High':>12} | {'Low':>12} | {'Close':>12} | {'Volume':>8} | {'VWAP':>12}"
    print(header)
    print("-" * len(header))
    for c in candles:
        print(
            f"{c['bucket_time']:<20} | "
            f"{format_price_cjk(c['open_price']):>12} | "
            f"{format_price_cjk(c['high_price']):>12} | "
            f"{format_price_cjk(c['low_price']):>12} | "
            f"{format_price_cjk(c['close_price']):>12} | "
            f"{c['volume']:>8} | "
            f"{format_price_cjk(c['vwap']):>12}"
        )


def handle_trades(args: argparse.Namespace) -> None:
    """Handles 'trades' subcommand."""
    trades = fetch_recent_trades(args.item, limit=args.limit)
    if not trades:
        print(f"No recent trades found for '{args.item}'.")
        return

    print(f"\n=== Recent Transacted Trades for '{args.item}' ===")
    header = f"{'Trade Time':<18} | {'Unit Price':>14} | {'Qty':>6} | {'Total Price':>14}"
    print(header)
    print("-" * len(header))
    for t in trades:
        print(
            f"{str(t.get('trade_time') or '-'):<18} | "
            f"{format_price_cjk(t['matched_unit_price']):>14} | "
            f"{t['quantity']:>6} | "
            f"{format_price_cjk(t.get('total_matched_price')):>14}"
        )


def handle_listings(args: argparse.Namespace) -> None:
    """Handles 'listings' subcommand."""
    listings = fetch_active_listings(args.item, limit=args.limit)
    if not listings:
        print(f"No active listings found for '{args.item}'.")
        return

    print(f"\n=== Active Sell Listings for '{args.item}' ===")
    header = f"{'Captured At':<20} | {'Unit Price':>14} | {'Qty':>6} | {'Total Price':>14} | {'Remaining':<10}"
    print(header)
    print("-" * len(header))
    for l in listings:
        print(
            f"{str(l.get('captured_at') or '-')[:19]:<20} | "
            f"{format_price_cjk(l['unit_price']):>14} | "
            f"{l['quantity']:>6} | "
            f"{format_price_cjk(l['total_price']):>14} | "
            f"{str(l.get('remaining_time') or '-'):<10}"
        )


def handle_due(args: argparse.Namespace) -> None:
    """Handles 'due' subcommand."""
    wm = WatchlistManager()
    due_items, wait_sec, next_item = wm.get_due_items()
    print(f"\n=== Due Items Status ===")
    print(f"Currently Due Items : {len(due_items)}")
    if due_items:
        for idx, it in enumerate(due_items, 1):
            print(f"  [{idx:02d}] {it}")
    if next_item:
        print(f"\nNext Due Item : '{next_item}' in {wait_sec / 60.0:.1f} minutes ({int(wait_sec)}s)")


def handle_evaluate(args: argparse.Namespace) -> None:
    """Handles 'evaluate' subcommand."""
    wm = WatchlistManager()
    res = wm.evaluate_and_update_watchlist()
    print("\n=== Watchlist Velocity Tier Evaluation ===")
    print(f"Total Watchlist Items : {res.get('total_items', 0)}")
    tier_counts = res.get("tier_counts", {})
    for t in sorted(tier_counts.keys()):
        print(f"  Tier {t}: {tier_counts[t]} items")
    if res.get("promotions"):
        print(f"Promotions ({len(res['promotions'])}):")
        for p in res["promotions"]:
            print(f"  ⬆ {p[0]} (Tier {p[1]} -> Tier {p[2]})")
    if res.get("demotions"):
        print(f"Demotions ({len(res['demotions'])}):")
        for d in res["demotions"]:
            print(f"  ⬇ {d[0]} (Tier {d[1]} -> Tier {d[2]})")


def main() -> None:
    """CLI router for query subcommands."""
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Artale Market Data Inspection CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: kline
    kline_p = subparsers.add_parser("kline", help="Inspect candlestick OHLCV data.")
    kline_p.add_argument("item", type=str, help="Item name to query.")
    kline_p.add_argument(
        "--timeframe", choices=["1h", "4h", "1d"], default="1h", help="Interval."
    )
    kline_p.add_argument(
        "--limit", type=int, default=20, help="Number of candles to display."
    )
    kline_p.set_defaults(func=handle_kline)

    # Subcommand: trades
    trades_p = subparsers.add_parser("trades", help="Inspect completed historical trades.")
    trades_p.add_argument("item", type=str, help="Item name to query.")
    trades_p.add_argument(
        "--limit", type=int, default=20, help="Number of trade rows to display."
    )
    trades_p.set_defaults(func=handle_trades)

    # Subcommand: listings
    listings_p = subparsers.add_parser("listings", help="Inspect active order book listings.")
    listings_p.add_argument("item", type=str, help="Item name to query.")
    listings_p.add_argument(
        "--limit", type=int, default=20, help="Number of listings to display."
    )
    listings_p.set_defaults(func=handle_listings)

    # Subcommand: due
    due_p = subparsers.add_parser("due", help="Check items currently due for collection.")
    due_p.set_defaults(func=handle_due)

    # Subcommand: evaluate
    eval_p = subparsers.add_parser("evaluate", help="Re-evaluate watchlist priority tiers.")
    eval_p.set_defaults(func=handle_evaluate)

    args = parser.parse_args()
    setup_logging()
    args.func(args)


if __name__ == "__main__":
    main()
