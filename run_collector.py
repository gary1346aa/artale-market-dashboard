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
from typing import Dict, List, Optional, Tuple, Union

from config.settings import DEFAULT_INSTANCES, WATCHLIST_PATH, setup_logging
from core.watchlist import WatchlistManager, get_due_items
from driver.emulator_controller import EmulatorController
from driver.window_driver import WindowManager, WindowSelector
from pipeline.collector import MarketCollector
from pipeline.parallel_collector import ParallelCollector

_logger = logging.getLogger("ArtaleCollector")


def parallel_bootstrap_devices(devices: List[str], max_timeout_sec: int = 160) -> List[str]:
    """Runs GameBootstrapper concurrently across the given ADB devices.

    Returns a list of device IDs that successfully reached Free Market.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from driver.adb_driver import AdbDriver
    from driver.game_bootstrapper import GameBootstrapper, ScreenState, detect_screen_state

    from config.settings import DEVICE_INSTANCE_MAP, pad_display_width

    _logger.info(f"Initiating parallel Free Market bootstrap for instances: {[DEVICE_INSTANCE_MAP.get(d, d) for d in devices]}")
    healthy_devices: List[str] = []

    def _boot_single(dev: str) -> Tuple[str, bool]:
        drv = AdbDriver(device_id=dev)
        bootstrapper = GameBootstrapper(drv)
        ok = bootstrapper.bootstrap_to_free_market(clean_reboot=False, max_timeout_sec=max_timeout_sec)
        final_state = detect_screen_state(drv.screencap())
        is_ready = ok or (final_state == ScreenState.STATE_FREE_MARKET)
        return dev, is_ready

    with ThreadPoolExecutor(max_workers=len(devices)) as executor:
        futures = {executor.submit(_boot_single, d): d for d in devices}
        for fut in as_completed(futures):
            dev, ready = fut.result()
            inst_name = DEVICE_INSTANCE_MAP.get(dev, dev)
            tag = pad_display_width(inst_name, 6)
            if ready:
                _logger.info(f"[{tag}] Bootstrap successful. Device ready.")
                healthy_devices.append(dev)
            else:
                _logger.error(f"[{tag}] Bootstrap failed. Excluding device from batch pool.")

    return healthy_devices


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
        "--cold-boot",
        action="store_true",
        help="Cold-boot target LDPlayer emulators if they are not already running.",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Bootstrap emulator(s) through Artale to Free Market before scanning.",
    )
    parser.add_argument(
        "--kill-after",
        action="store_true",
        help="Terminate emulators upon batch completion or error to save power.",
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

    ctrl = EmulatorController()
    healthy_devices: Optional[List[str]] = None

    try:
        # Pre-check for due mode without loop: if nothing is due, exit immediately before booting
        if args.due and not args.loop:
            wm = WatchlistManager(watchlist_path=Path(args.watchlist))
            due_items, wait_sec, next_it = wm.get_due_items()
            if not due_items:
                _logger.info(
                    f"All items up to date. Next due: '{next_it}' in {wait_sec / 60.0:.1f} minutes."
                )
                return

        # Helper to select single vs parallel scanner with autonomous per-instance lifecycle
        def get_scanner() -> ParallelCollector:
            max_w = (
                args.parallel
                if (args.parallel is not None and args.parallel > 0)
                else None
            )
            insts = [args.instance] if args.instance else None
            return ParallelCollector(
                max_workers=max_w,
                instances=insts,
                use_adb=True,
                cold_boot=args.cold_boot,
                bootstrap=args.bootstrap,
                kill_after=args.kill_after,
                controller=ctrl,
            )

        # 1. Passive Mode
        if args.mode == "passive":
            from pipeline.passive_monitor import PassiveMarketMonitor

            monitor = PassiveMarketMonitor(window_mgr=target_win_mgr)
            monitor.start_listener()
            return

        # 2. Single Item Query Mode
        if args.query:
            inst = args.instance or "槍手"
            if args.cold_boot:
                _logger.info(f"Cold-booting instance '{inst}'...")
                ctrl.launch_instance(inst)
            if args.bootstrap:
                from driver.adb_driver import AdbDriver
                from driver.game_bootstrapper import GameBootstrapper
                from pipeline.collector import INSTANCE_TO_DEVICE
                dev = INSTANCE_TO_DEVICE.get(inst, "emulator-5560")
                bootstrapper = GameBootstrapper(
                    AdbDriver(device_id=dev), controller=ctrl, instance_name=inst
                )
                bootstrapper.bootstrap_to_free_market()

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
                if args.kill_after:
                    ctrl.quit_instance(inst)
            return

        # 3. Due Items Collection Mode
        if args.due:
            wm = WatchlistManager(watchlist_path=Path(args.watchlist))
            if args.loop:
                _logger.info("Starting continuous schedule loop for due items...")
                while True:
                    due_items, wait_sec, next_it = wm.get_due_items()
                    if due_items:
                        _logger.info(
                            f"Found {len(due_items)} items currently due. Scanning..."
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
                            f"All items up to date. Next due: '{next_it}' in {wait_sec / 60.0:.1f} min."
                        )
                        time.sleep(min(wait_sec, 60.0))
            else:
                _logger.info(f"Found {len(due_items)} items due for update.")
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
            _logger.error(f"Watchlist file '{args.watchlist}' not found.")
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
                    f"Filtered watchlist to Tier {args.tier} ({len(items)} items)."
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

    finally:
        if args.kill_after:
            if args.instance:
                if ctrl.is_running(args.instance):
                    ctrl.quit_instance(args.instance)
            else:
                from driver.adb_driver import AdbDriver
                attached = AdbDriver.list_attached_devices()
                if any(d in attached for d in ["emulator-5560", "emulator-5562", "emulator-5568"]):
                    ctrl.quit_all()


if __name__ == "__main__":
    main()
