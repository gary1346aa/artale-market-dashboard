"""CLI entry point for running Artale Market Tracker collection pipelines.

Supports single-item queries, scheduled due items based on velocity tiers,
and multi-instance dynamic work-stealing parallel execution.
"""

import argparse
import json
import logging
from pathlib import Path
import sys
import time
from typing import List

from config.settings import DEFAULT_INSTANCES, WATCHLIST_PATH, setup_logging
from core.watchlist import WatchlistManager, get_due_items
from pipeline.collector import MarketCollector
from pipeline.parallel_collector import ParallelCollector

_logger = logging.getLogger(__name__)


def main() -> None:
    """Main CLI execution router."""
    setup_logging(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Artale Market Tracker - Collection CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="auto",
        choices=["auto", "manual", "catalog", "passive"],
        help="Operating mode (legacy compatibility).",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="auto",
        choices=["auto", "manual", "catalog", "passive"],
        help="Operating mode (legacy compatibility).",
    )
    parser.add_argument(
        "--query",
        type=str,
        help="Collect market data for a single specific item name.",
    )
    parser.add_argument(
        "--due",
        action="store_true",
        help="Collect only items currently due according to velocity tier intervals.",
    )
    parser.add_argument(
        "--watchlist",
        action="store_true",
        help="Collect all items in items_watchlist.json sequentially.",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run collection using multi-instance work-stealing across emulators.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Maximum parallel worker instances to utilize.",
    )
    parser.add_argument(
        "--instance",
        type=str,
        default="槍手",
        help="LDPlayer instance name to use for single-instance collection.",
    )
    parser.add_argument(
        "--tab",
        choices=["both", "asks", "trades"],
        default="both",
        help="Which tab(s) to collect: asks (查詢), trades (市價), or both.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=2,
        help="Maximum pages to collect per query tab.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Continuously poll and collect due items on schedule.",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Auto-launch and bootstrap instance to Free Market if offline or not in market.",
    )
    parser.add_argument(
        "--reboot",
        action="store_true",
        help="Kill and cleanly reboot the emulator instance before bootstrapping.",
    )

    args = parser.parse_args()
    setup_logging(level=logging.INFO)

    # 1. Single Item Query Mode
    if args.query:
        _logger.info("Executing single item collection: '%s'", args.query)
        collector = MarketCollector(
            instance_name=args.instance,
            use_adb=True,
            auto_bootstrap=args.bootstrap,
            clean_reboot=args.reboot,
        )
        try:
            collector.run_query_collection(
                args.query, max_pages=args.max_pages, target_tab=args.tab
            )
        finally:
            collector.shutdown()
        return

    # 2. Continuous Loop or Single Pass for Due Items
    if args.due:
        wm = WatchlistManager()
        if args.loop:
            _logger.info("Starting continuous schedule loop for due items...")
            while True:
                due_items, wait_sec, next_item = wm.get_due_items()
                if due_items:
                    _logger.info(
                        "Found %d items currently due: %s",
                        len(due_items),
                        due_items[:5],
                    )
                    if args.parallel:
                        pc = ParallelCollector(max_workers=args.max_workers)
                        pc.run_catalog_scan(
                            due_items,
                            max_pages=args.max_pages,
                            target_tab=args.tab,
                        )
                    else:
                        collector = MarketCollector(
                            instance_name=args.instance,
                            use_adb=True,
                            auto_bootstrap=args.bootstrap,
                            clean_reboot=args.reboot,
                        )
                        try:
                            collector.run_catalog_scan(
                                due_items,
                                max_pages_per_query=args.max_pages,
                                target_tab=args.tab,
                            )
                        finally:
                            collector.shutdown()
                else:
                    _logger.info(
                        "No items due. Next due: '%s' in %.1f minutes. Sleeping...",
                        next_item,
                        wait_sec / 60.0,
                    )
                    time.sleep(min(wait_sec, 60.0))
        else:
            due_items, wait_sec, next_item = wm.get_due_items()
            _logger.info("Found %d items currently due.", len(due_items))
            if not due_items:
                _logger.info(
                    "Next due item: '%s' in %.1f minutes.",
                    next_item,
                    wait_sec / 60.0,
                )
                return

            if args.parallel:
                pc = ParallelCollector(max_workers=args.max_workers)
                pc.run_catalog_scan(
                    due_items, max_pages=args.max_pages, target_tab=args.tab
                )
            else:
                collector = MarketCollector(
                    instance_name=args.instance,
                    use_adb=True,
                    auto_bootstrap=args.bootstrap,
                    clean_reboot=args.reboot,
                )
                try:
                    collector.run_catalog_scan(
                        due_items,
                        max_pages_per_query=args.max_pages,
                        target_tab=args.tab,
                    )
                finally:
                    collector.shutdown()
        return

    # 3. Full Watchlist Mode
    if args.watchlist:
        if not WATCHLIST_PATH.exists():
            _logger.error("Watchlist file not found: %s", WATCHLIST_PATH)
            sys.exit(1)

        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
            items = list(raw.keys()) if isinstance(raw, dict) else raw

        _logger.info("Loaded %d items from watchlist.", len(items))
        if args.parallel:
            pc = ParallelCollector(max_workers=args.max_workers)
            pc.run_catalog_scan(
                items, max_pages=args.max_pages, target_tab=args.tab
            )
        else:
            collector = MarketCollector(
                instance_name=args.instance,
                use_adb=True,
                auto_bootstrap=args.bootstrap,
                clean_reboot=args.reboot,
            )
            try:
                collector.run_catalog_scan(
                    items,
                    max_pages_per_query=args.max_pages,
                    target_tab=args.tab,
                )
            finally:
                collector.shutdown()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
