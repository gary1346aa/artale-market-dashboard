"""Root CLI runner for Artale Market Tracker collection pipelines.

Supports due-only collection, single-item queries, tier-filtered catalogs,
and multi-emulator dynamic work-stealing parallel execution.
"""

import argparse
import json
import logging
from pathlib import Path
import sys
import time
from typing import List, Optional, Union

from config.settings import DEFAULT_INSTANCES, WATCHLIST_PATH, setup_logging
from core.watchlist import WatchlistManager, get_due_items
from driver.window_driver import WindowManager, WindowSelector
from pipeline.collector import MarketCollector
from pipeline.parallel_collector import ParallelCollector

_logger = logging.getLogger("ArtaleCollector")


def main() -> None:
    """Main collection entry point."""
    setup_logging(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Artale Market Data Collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="auto",
        choices=["auto", "manual", "catalog", "passive"],
        help="Operating mode: 'auto' (navigates & collects automatically), 'manual', 'catalog', or 'passive'.",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Single search query (e.g. '頭盔', '力量水晶').",
    )
    parser.add_argument(
        "--due",
        action="store_true",
        help="Scan only items currently due based on tier polling intervals.",
    )
    parser.add_argument(
        "--watchlist",
        type=str,
        default=str(WATCHLIST_PATH),
        help="Path to JSON file containing watchlist items.",
    )
    parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3, 4],
        default=None,
        help="Filter watchlist to only scan items of a specific tier.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=2,
        help="Number of pages to collect per query tab (default: 2).",
    )
    parser.add_argument(
        "--target-tab",
        choices=["asks", "trades", "both"],
        default="both",
        help="Which auction tab(s) to query: 'asks', 'trades', or 'both'.",
    )
    parser.add_argument(
        "--instance",
        type=str,
        default=None,
        help="Target LDPlayer instance name (e.g. '槍手', '祈禱機').",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="1-based index in watchlist to start scanning from.",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        nargs="?",
        const=0,
        default=None,
        help="Run multi-worker parallel collection (optional: max workers).",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Continuously poll and collect due items on schedule.",
    )
    parser.add_argument(
        "--select-window",
        action="store_true",
        help="Interactively select a target window handle.",
    )

    args = parser.parse_args()
    setup_logging(level=logging.INFO)

    target_win_mgr: Optional[WindowManager] = None
    if args.select_window:
        selected = WindowSelector.find_by_keywords(
            ["LDPlayer", "雷電", "dnplayer", "leidian", "Artale"]
        )
        if selected:
            target_win_mgr = WindowManager(target_hwnd=selected[0]["hwnd"])

    # 1. Passive Mode
    if args.mode == "passive":
        from pipeline.passive_monitor import PassiveMarketMonitor

        monitor = PassiveMarketMonitor(window_mgr=target_win_mgr)
        monitor.start_listener()
        return

    # 2. Single Item Query Mode
    if args.query:
        collector = MarketCollector(
            window_mgr=target_win_mgr,
            instance_name=args.instance,
            use_adb=True,
            allow_instance_rotation=False,
        )
        try:
            collector.run_query_collection(
                args.query, max_pages=args.pages, target_tab=args.target_tab
            )
        finally:
            collector.shutdown()
        return

    # 3. Helper to select single vs parallel scanner
    def get_scanner() -> Union[MarketCollector, ParallelCollector]:
        if args.instance is None and (args.parallel is None or args.parallel != 1):
            max_w = (
                args.parallel
                if (args.parallel is not None and args.parallel > 0)
                else None
            )
            return ParallelCollector(max_workers=max_w, use_adb=True)
        return MarketCollector(
            window_mgr=target_win_mgr,
            instance_name=args.instance,
            use_adb=True,
        )

    # 3. Due Items Collection Mode
    if args.due:
        wm = WatchlistManager(watchlist_path=Path(args.watchlist))
        if args.loop:
            _logger.info("Starting continuous schedule loop for due items...")
            while True:
                due_items, wait_sec, next_it = wm.get_due_items()
                if due_items:
                    _logger.info(
                        "Found %d items currently due. Scanning...",
                        len(due_items),
                    )
                    scanner = get_scanner()
                    try:
                        if isinstance(scanner, ParallelCollector):
                            scanner.run_catalog_scan(
                                due_items,
                                max_pages=args.pages,
                                target_tab=args.target_tab,
                            )
                        else:
                            scanner.run_catalog_scan(
                                due_items,
                                max_pages_per_query=args.pages,
                                target_tab=args.target_tab,
                            )
                    finally:
                        if hasattr(scanner, "shutdown"):
                            scanner.shutdown()
                else:
                    _logger.info(
                        "All items up to date. Next due: '%s' in %.1f min.",
                        next_it,
                        wait_sec / 60.0,
                    )
                    time.sleep(min(wait_sec, 60.0))
        else:
            due_items, wait_sec, next_it = wm.get_due_items()
            if not due_items:
                _logger.info(
                    "All items up to date! Next due: '%s' in %.1f minutes.",
                    next_it,
                    wait_sec / 60.0,
                )
                return

            _logger.info("Found %d items due to update.", len(due_items))
            scanner = get_scanner()
            try:
                if isinstance(scanner, ParallelCollector):
                    scanner.run_catalog_scan(
                        due_items,
                        max_pages=args.pages,
                        target_tab=args.target_tab,
                        start_index=args.start_index,
                    )
                else:
                    scanner.run_catalog_scan(
                        due_items,
                        max_pages_per_query=args.pages,
                        target_tab=args.target_tab,
                        start_index=args.start_index,
                    )
            finally:
                if hasattr(scanner, "shutdown"):
                    scanner.shutdown()
            _logger.info("Due collection round completed.")
            return

    # 4. Watchlist / Catalog Scan Mode
    wl_path = Path(args.watchlist)
    if not wl_path.exists():
        _logger.error("Watchlist file '%s' not found.", args.watchlist)
        return

    with open(wl_path, "r", encoding="utf-8") as f:
        raw_wl = json.load(f)

    if isinstance(raw_wl, dict):
        if args.tier:
            items = [
                k
                for k, v in raw_wl.items()
                if (v.get("tier", 3) if isinstance(v, dict) else v) == args.tier
            ]
            _logger.info(
                "Filtered watchlist to Tier %d (%d items).",
                args.tier,
                len(items),
            )
        else:
            items = list(raw_wl.keys())
    else:
        items = raw_wl

    scanner = get_scanner()
    try:
        if isinstance(scanner, ParallelCollector):
            scanner.run_catalog_scan(
                items,
                max_pages=args.pages,
                target_tab=args.target_tab,
                start_index=args.start_index,
            )
        else:
            scanner.run_catalog_scan(
                items,
                max_pages_per_query=args.pages,
                target_tab=args.target_tab,
                start_index=args.start_index,
            )
    finally:
        if hasattr(scanner, "shutdown"):
            scanner.shutdown()


if __name__ == "__main__":
    main()
