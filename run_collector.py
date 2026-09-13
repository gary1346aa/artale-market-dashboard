import sys
import io
import json
import argparse
from pathlib import Path

# Ensure UTF-8 output in Windows PowerShell/CMD
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

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
        else:
            watchlist_path = Path(args.watchlist)
            if not watchlist_path.exists():
                print(f"Error: Watchlist file '{args.watchlist}' not found.")
                return
            with open(watchlist_path, "r", encoding="utf-8") as f:
                items = json.load(f)
            collector.run_catalog_scan(items, max_pages_per_query=args.pages, target_tab=args.target_tab)


if __name__ == "__main__":
    main()
