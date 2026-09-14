import sys
import io
import json
import argparse
from pathlib import Path

# Ensure UTF-8 output in Windows PowerShell/CMD
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s [%(levelname)s] %(message)s", force=True)

from src.collector import MarketCollector
from src.passive_monitor import PassiveMarketMonitor
from src.window_manager import WindowManager
from src.window_selector import WindowSelector

def main():
    parser = argparse.ArgumentParser(
        description="Artale Market Data Collector (Auto & Passive Modes)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactively choose the LDPlayer / Artale window from a list:
  python run_collector.py --select-window --mode auto --query "墜飾幸運卷軸30%"

  # Run in passive mode:
  python run_collector.py --select-window --mode passive
        """
    )
    parser.add_argument(
        "--select-window",
        action="store_true",
        help="Display an interactive list of all open windows/emulators to pick the exact game window"
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
    parser.add_argument(
        "--target-tab",
        choices=["asks", "trades", "both"],
        default="both",
        help="Which auction tab to query: 'asks' (only 查詢), 'trades' (only 市價), or 'both' (default)"
    )
    parser.add_argument(
        "--instance",
        type=str,
        default=None,
        help="Specific LDPlayer instance to target (e.g. '槍手', '祈禱機'). Default is auto-rotation based on available quota."
    )

    parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3, 4],
        default=None,
        help="Optional: Filter watchlist to only scan items belonging to a specific tier (1, 2, 3, or 4)"
    )
    parser.add_argument(
        "--due",
        action="store_true",
        help="Scan only items that are currently due for collection based on their tier interval and last_updated timestamp"
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="1-based index in watchlist to start/resume scanning from (default: 1)"
    )

    args = parser.parse_args()

    # Determine target window manager
    target_win_mgr = None
    if args.select_window:
        selected = WindowSelector.prompt_selection(keywords=["LDPlayer", "雷電", "dnplayer", "leidian", "Artale", "MapleStory"])
        if not selected:
            print("No window selected. Exiting.")
            return
        target_win_mgr = WindowManager(target_hwnd=selected["hwnd"])

    if args.mode == "passive":
        monitor = PassiveMarketMonitor(window_mgr=target_win_mgr)
        monitor.start_listener()
    else:
        collector = MarketCollector(window_mgr=target_win_mgr, instance_name=args.instance)
        if args.query:
            collector.run_query_collection(args.query, max_pages=args.pages, target_tab=args.target_tab)
            return

        watchlist_path = Path(args.watchlist)
        if not watchlist_path.exists():
            print(f"Error: Watchlist file '{args.watchlist}' not found.")
            return

        from src.tier_evaluator import get_due_items

        # 1. Due-Only Collection Mode (Scans only items whose time elapsed exceeds their tier interval)
        if args.due:
            due_items, wait_sec, next_item = get_due_items(watchlist_path)
            if not due_items:
                print(f"All items are up to date! Next item '{next_item}' will be due in {wait_sec/60:.1f} minutes.")
                return
            print(f"AUTO Mode: Found {len(due_items)} due items. Starting collection...")
            collector.run_catalog_scan(due_items, max_pages_per_query=args.pages, target_tab=args.target_tab, start_index=args.start_index)
            _, next_wait, next_item = get_due_items(watchlist_path)
            if next_item:
                print(f"Round completed. Next item '{next_item}' due in {next_wait/60:.1f} minutes.")
            return

        # 2. Standard / Tier-Filtered Catalog Scan
        with open(watchlist_path, "r", encoding="utf-8") as f:
            raw_wl = json.load(f)

        if isinstance(raw_wl, dict):
            if args.tier:
                items = [
                    k for k, v in raw_wl.items()
                    if (v.get("tier", 3) if isinstance(v, dict) else v) == args.tier
                ]
                print(f"Filtered watchlist to Tier {args.tier} ({len(items)} items).")
            else:
                items = list(raw_wl.keys())
        else:
            items = raw_wl

        collector.run_catalog_scan(items, max_pages_per_query=args.pages, target_tab=args.target_tab, start_index=args.start_index)


if __name__ == "__main__":
    main()
