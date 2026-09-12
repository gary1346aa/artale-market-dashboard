import sys
import io
import json
import argparse
from pathlib import Path

# Ensure UTF-8 output in Windows PowerShell/CMD
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.collector import MarketCollector
from src.passive_monitor import PassiveMarketMonitor

def main():
    parser = argparse.ArgumentParser(
        description="Artale Market Data Collector (Auto & Passive Modes)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_collector.py --mode passive
    Runs in passive mode (Zero botting risk). Press [F9] to capture active view, or [F10] to auto-record.

  python run_collector.py --mode auto --query "頭盔"
    Focuses Artale window, searches for '頭盔', collects active listings and match prices across 2 pages.

  python run_collector.py --mode auto --watchlist items_watchlist.json --pages 2
    Iterates through the entire watchlist, collecting both sell orders and completed trades.
        """
    )
    parser.add_argument(
        "--mode",
        choices=["passive", "auto"],
        default="passive",
        help="Operating mode: 'passive' (hotkey capture, 0 synthetic input) or 'auto' (navigates & searches automatically)"
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Single search query for auto mode (e.g. '頭盔', '卷軸')"
    )
    parser.add_argument(
        "--watchlist",
        type=str,
        default="items_watchlist.json",
        help="Path to JSON file containing list of search keywords (default: items_watchlist.json)"
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=2,
        help="Number of pages to paginate and collect per query (default: 2)"
    )

    args = parser.parse_args()

    if args.mode == "passive":
        monitor = PassiveMarketMonitor()
        monitor.start_listener()
    else:
        collector = MarketCollector()
        if args.query:
            collector.run_query_collection(args.query, max_pages=args.pages, check_both_tabs=True)
        else:
            watchlist_path = Path(args.watchlist)
            if not watchlist_path.exists():
                print(f"Error: Watchlist file '{args.watchlist}' not found.")
                return
            with open(watchlist_path, "r", encoding="utf-8") as f:
                items = json.load(f)
            collector.run_catalog_scan(items, max_pages_per_query=args.pages)

if __name__ == "__main__":
    main()
