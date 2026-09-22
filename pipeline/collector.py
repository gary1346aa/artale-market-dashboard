"""Market collection state machine and query automation.

Coordinates screen capture, tab navigation, price sort order verification,
stateless live screen quota validation (quota >= 2), and background OCR streaming.
"""

from datetime import datetime, timedelta
import logging
from pathlib import Path
import subprocess
import time
from typing import Dict, List, Optional

from PIL import Image

from config.coordinates import (
    POS_FIRST_PAGE,
    POS_MARKET_TAB,
    POS_NEXT_PAGE,
    POS_PRICE_HEADER,
    POS_QUERY_TAB,
    POS_QUICK_SEARCH,
    Point,
)
from config.settings import (
    DEFAULT_ADB_PATH,
    DEFAULT_INSTANCES,
    LDCONSOLE_PATH,
    get_seconds_until_next_8am,
)
from core.watchlist import update_item_timestamp
from driver.adb_driver import AdbDriver
from driver.window_driver import WindowManager
from pipeline.async_worker import AsyncOcrWorker
from recognition.digit_engine import parse_quota_header
from recognition.table_parser import MarketParser
from storage.aggregator import KlineAggregator
from storage.database import init_db, save_active_listings, save_matched_trades

_logger = logging.getLogger(__name__)


def discover_instances() -> Dict[str, str]:
    """Auto-discovers LDPlayer instances and maps names to ADB device serials.

    Returns:
        Dict mapping instance name to ADB device string (e.g. 'emulator-5558').
    """
    mapping: Dict[str, str] = {
        "祈禱機": "emulator-5558",
        "槍手": "emulator-5560",
        "打火機": "emulator-5562",
        "弩手": "emulator-5568",
    }
    try:
        p = subprocess.run(
            [LDCONSOLE_PATH, "list2"],
            capture_output=True,
            timeout=3,
            check=False,
        )
        if p.returncode == 0:
            for line in p.stdout.decode("utf-8", errors="ignore").splitlines():
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    idx, name = parts[0], parts[1]
                    port = 5554 + int(idx) * 2
                    mapping[name] = f"emulator-{port}"
    except Exception as err:
        _logger.debug(f"Failed to query ldconsole for instances: {err}")
    return mapping


INSTANCE_TO_DEVICE = discover_instances()


def read_quota_from_frame(frame: Optional[Image.Image]) -> Optional[int]:
    """Extracts remaining quota count deterministically from screen frame.

    Args:
        frame: PIL RGB Image.

    Returns:
        Remaining search integer or None.
    """
    if frame is None:
        return None
    try:
        res = parse_quota_header(frame)
        if res is not None:
            remaining, _ = res
            return remaining
    except Exception as err:
        _logger.debug(f"Error parsing quota header: {err}")
    return None


def pause_until_next_8am(instance_name: str = "") -> None:
    """Pauses execution until 08:00 AM server quota reset the next day.

    Args:
        instance_name: Optional instance label for logging.
    """
    wait_sec = get_seconds_until_next_8am()
    hours = wait_sec / 3600.0
    prefix = f"[{instance_name}] " if instance_name else ""
    _logger.info(
        f"{prefix}Quota exhausted (< 2). Pausing instance until 08:00 AM reset ({hours:.1f} hours, {int(wait_sec)}s)..."
    )
    wake_time = time.time() + wait_sec
    while time.time() < wake_time:
        remaining = wake_time - time.time()
        time.sleep(min(30.0, remaining))
    _logger.info(f"{prefix}08:00 AM server reset reached. Resuming instance.")


class MarketCollector:
    """Automates market scanning, tab navigation, OCR data collection, and persistence.

    Enforces stateless quota verification: checks live screen quota >= 2 once per item.
    Pauses until 08:00 AM reset on quota exhaustion.

    Attributes:
        use_adb: Whether to use ADB driver (default True).
        allow_instance_rotation: Whether to rotate to other instances upon quota exhaustion.
        current_instance: Name of the active instance.
        adb: AdbDriver instance.
        win_mgr: WindowManager instance for host fallback.
        aggregator: KlineAggregator for candlestick building.
        ocr_worker: AsyncOcrWorker for pipelined background parsing.
    """

    def __init__(
        self,
        window_mgr: Optional[WindowManager] = None,
        instance_name: Optional[str] = None,
        use_adb: bool = True,
        allow_instance_rotation: bool = True,
        auto_bootstrap: bool = False,
        clean_reboot: bool = False,
    ) -> None:
        """Initializes MarketCollector with drivers and background workers."""
        self.use_adb = use_adb
        self.allow_instance_rotation = allow_instance_rotation
        self.auto_bootstrap = auto_bootstrap
        self.clean_reboot = clean_reboot
        self.current_instance = instance_name or "槍手"
        self.win_mgr = window_mgr or WindowManager(
            title_keywords=[self.current_instance, "LDPlayer", "雷電模擬器", "雷電"]
        )
        self.aggregator = KlineAggregator()
        self.ocr_worker = AsyncOcrWorker()

        if self.use_adb:
            attached = AdbDriver.list_attached_devices()
            rev_map = {v: k for k, v in INSTANCE_TO_DEVICE.items()}
            dev_id = INSTANCE_TO_DEVICE.get(self.current_instance)
            if (not instance_name or dev_id not in attached) and attached:
                dev_id = attached[0]
                self.current_instance = rev_map.get(dev_id, dev_id)
            elif not dev_id:
                dev_id = attached[0] if attached else "emulator-5560"
            self.adb = AdbDriver(device_id=dev_id)
            _logger.debug(
                f"Initialized ADB background engine on device '{dev_id}' for '{self.current_instance}'."
            )
        else:
            self.adb = None

        init_db()

    def capture_frame(self) -> Optional[Image.Image]:
        """Captures display buffer from active driver."""
        if self.use_adb and self.adb:
            return self.adb.screencap()
        return self.win_mgr.capture_frame() if self.win_mgr else None

    def switch_to_instance(self, instance_name: str) -> bool:
        """Switches active tracker to another LDPlayer instance.

        Args:
            instance_name: Name of target instance.

        Returns:
            True on successful switch and focus.
        """
        _logger.debug(f"Switching active tracker to instance '{instance_name}'...")
        self.current_instance = instance_name

        if self.use_adb and self.adb:
            dev_id = INSTANCE_TO_DEVICE.get(instance_name, "emulator-5558")
            self.adb = AdbDriver(device_id=dev_id)
            _logger.debug(f"Switched ADB device to '{dev_id}' ({instance_name}).")
        else:
            self.win_mgr = WindowManager(title_keywords=[instance_name])

        self.ensure_focus()
        _logger.debug(f"Switched successfully to '{instance_name}'.")
        return True

    def get_screen_quota(
        self, frame: Optional[Image.Image] = None
    ) -> Optional[int]:
        """Reads in-game quota header directly from live screen frame.

        Returns:
            Remaining quota integer, or None.
        """
        if frame is None:
            frame = self.capture_frame()
        if not frame:
            return None
        rem = read_quota_from_frame(frame)
        if rem is None and frame is not None:
            fresh = self.capture_frame()
            if fresh:
                rem = read_quota_from_frame(fresh)
        return rem

    def rotate_to_next_available(self, required: int = 2) -> bool:
        """Rotates to next attached instance and checks its live screen quota.

        Args:
            required: Minimum quota required (default 2).

        Returns:
            True if an instance with sufficient quota was found and selected.
        """
        if not self.use_adb:
            return False
        attached = AdbDriver.list_attached_devices()
        candidates = [
            name
            for name, dev in INSTANCE_TO_DEVICE.items()
            if dev in attached and name != self.current_instance
        ]
        for name in candidates:
            _logger.debug(f"Checking alternative candidate instance '{name}'...")
            if not self.switch_to_instance(name):
                continue
            rem = self.get_screen_quota()
            if rem is not None and rem >= required:
                _logger.info(
                    f"Switched to '{name}' with {rem}/500 live screen quota."
                )
                return True
            _logger.warning(
                f"Candidate '{name}' has insufficient screen quota ({rem}/500)."
            )
        return False

    def ensure_focus(self, max_retries: int = 3) -> bool:
        """Verifies Auction House is open and ready on the current instance.

        Args:
            max_retries: Maximum attempts to open Auction House.

        Returns:
            True if Auction House is ready, False otherwise.
        """
        if self.use_adb and self.adb:
            # Check if instance is in neither Auction House nor Free Market
            if not self.adb.is_auction_open() and not self.adb.is_free_market():
                if self.auto_bootstrap:
                    _logger.info(
                        f"[{self.current_instance}] Instance neither in Auction nor Free Market. Bootstrapping..."
                    )
                    from driver.game_bootstrapper import GameBootstrapper

                    bootstrapper = GameBootstrapper(
                        self.adb, instance_name=self.current_instance
                    )
                    if not bootstrapper.bootstrap_to_free_market(
                        clean_reboot=self.clean_reboot
                    ):
                        _logger.error(
                            f"Failed to bootstrap instance '{self.current_instance}' to Free Market."
                        )
                        return False
                else:
                    _logger.error(
                        f"[{self.current_instance}] Instance is neither in Auction House nor Free Market. "
                        "Pass --bootstrap to auto-launch and enter Free Market."
                    )
                    return False

            for attempt in range(1, max_retries + 1):
                if self.adb.is_auction_open():
                    rem = self.get_screen_quota()
                    if rem is not None:
                        _logger.debug(
                            f"[{self.current_instance}] Auction House ready (Live screen quota: {rem}/500)."
                        )
                    return True

                _logger.debug(
                    f"[{self.current_instance}] ({self.adb.device_id}) opening Auction House (attempt {attempt}/{max_retries})..."
                )
                if self.adb.enter_auction_from_free_market(max_wait_sec=8):
                    _logger.debug(
                        f"Entered Auction House on '{self.current_instance}'."
                    )
                    rem = self.get_screen_quota()
                    if rem is not None:
                        _logger.debug(
                            f"[{self.current_instance}] Live screen quota: {rem}/500."
                        )
                    return True

                if attempt < max_retries:
                    time.sleep(2.0)

            _logger.warning(
                f"[{self.current_instance}] ({self.adb.device_id}) failed to enter Auction House after {max_retries} attempts."
            )
            return False

        if not self.win_mgr.find_window():
            _logger.error(
                f"Window for '{self.current_instance}' not detected."
            )
            return False

        return True

    def leave_auction(self) -> bool:
        """Safely exits Auction House to Free Market to prevent timeout."""
        if self.use_adb and self.adb:
            return self.adb.leave_auction_to_free_market()
        return True

    def is_auction_open(self) -> bool:
        """Checks whether Auction House is currently open."""
        if self.use_adb and self.adb:
            return self.adb.is_auction_open()
        frame = self.capture_frame()
        if not frame or frame.width < 1000 or frame.height < 600:
            return False
        return True

    def switch_to_tab(self, target_tab: str) -> bool:
        """Switches between 'query' (查詢) and 'market' (市價) tabs.

        Args:
            target_tab: 'query' or 'market'.

        Returns:
            True on completion.
        """
        pt = POS_QUERY_TAB if target_tab == "query" else POS_MARKET_TAB
        if self.use_adb and self.adb:
            self.adb.tap(pt.x, pt.y)
            time.sleep(0.6)
        return True

    def execute_search(
        self, keyword: str, reuse_existing: bool = False
    ) -> bool:
        """Submits keyword search in the Auction House quick search bar.

        Args:
            keyword: Item name string.
            reuse_existing: Whether to skip retyping and submit existing search.

        Returns:
            True on successful submission.
        """
        if not self.is_auction_open():
            _logger.error("SAFETY GUARD: Auction House closed. Refusing to search.")
            return False

        if self.use_adb and self.adb:
            if reuse_existing:
                _logger.debug(
                    f"Reusing search bar keyword: '{keyword}' (fast submit)"
                )
                self.adb.tap(POS_QUICK_SEARCH.x, POS_QUICK_SEARCH.y)
                time.sleep(0.2)
                self.adb.press_enter()
                time.sleep(0.4)
                self.adb.handle_lingering_popups()
            else:
                _logger.debug(f"Searching for item via ADB: '{keyword}'")
                self.adb.tap(POS_QUICK_SEARCH.x, POS_QUICK_SEARCH.y)
                time.sleep(0.25)
                self.adb.input_chinese(keyword)
                time.sleep(0.15)
                self.adb.press_enter()
                time.sleep(0.4)
                self.adb.handle_lingering_popups()
            time.sleep(0.2)
            return True
        return False

    def paginate_and_scrape(
        self,
        max_pages: int = 3,
        is_market: bool = False,
        initial_frame: Optional[Image.Image] = None,
        item_name: Optional[str] = None,
    ) -> Optional[Image.Image]:
        """Scrapes tab pages using pipelined background OCR streaming.

        Args:
            max_pages: Upper bound on pages to flip.
            is_market: True if scanning 市價 tab, False for 查詢 tab.
            initial_frame: Pre-captured frame from sort check.
            item_name: Item name.

        Returns:
            Final captured PIL Image or None.
        """
        effective_max = 50 if is_market else max_pages
        tab = "market" if is_market else "query"
        self.ocr_worker.reset_signature()

        frame1 = initial_frame if initial_frame is not None else self.capture_frame()
        if not frame1:
            _logger.warning("Frame capture returned empty on page 1.")
            return None

        parser1 = MarketParser(frame1, item_name=item_name)
        pagination = parser1.parse_pagination()

        if not pagination:
            time.sleep(0.35)
            fresh = self.capture_frame()
            if fresh:
                frame1 = fresh
                parser1 = MarketParser(frame1, item_name=item_name)
                pagination = parser1.parse_pagination()

        last_frame = frame1

        if pagination:
            curr_p, total_p = pagination
            target_pages = min(total_p, effective_max)
            _logger.debug(
                f"Page 1 Micro-OCR: Detected page {curr_p}/{total_p}. Target: {target_pages} pages."
            )

            self.ocr_worker.submit(
                frame1,
                tab=tab,
                page_num=1,
                item_name=item_name,
                device_id=self.adb.device_id if self.adb else None,
            )

            if target_pages > 1:
                for page_idx in range(2, target_pages + 1):
                    if self.use_adb and self.adb:
                        self.adb.tap(POS_NEXT_PAGE.x, POS_NEXT_PAGE.y)
                        time.sleep(0.30)

                    frame = self.capture_frame()
                    if not frame:
                        _logger.warning(
                            f"Frame capture empty on page {page_idx}."
                        )
                        break

                    last_frame = frame
                    self.ocr_worker.submit(
                        frame,
                        tab=tab,
                        page_num=page_idx,
                        item_name=item_name,
                        device_id=self.adb.device_id if self.adb else None,
                    )
            else:
                _logger.debug(
                    f"Single page result ({curr_p}/{total_p})."
                )

            self.ocr_worker.wait_all()
            return last_frame

        # Fallback loop
        return self._fallback_paginate_and_scrape(
            max_pages=max_pages, is_market=is_market, item_name=item_name
        )

    def _fallback_paginate_and_scrape(
        self,
        max_pages: int = 3,
        is_market: bool = False,
        item_name: Optional[str] = None,
    ) -> Optional[Image.Image]:
        """Synchronous fallback pagination when Page 1 control cannot be read."""
        effective_max = 50 if is_market else max_pages
        last_frame = None

        for page_idx in range(1, effective_max + 1):
            frame = self.capture_frame()
            if not frame:
                break
            last_frame = frame

            parser = MarketParser(frame, item_name=item_name)
            res = parser.parse()
            records = res.get("records", [])
            tab = res.get("tab", "query")

            if tab == "market":
                save_matched_trades(records)
            else:
                save_active_listings(records)

            if not records and page_idx > 1:
                break

            pagination = res.get("pagination")
            if pagination and pagination[0] >= pagination[1]:
                break

            if page_idx >= effective_max:
                break

            if self.use_adb and self.adb:
                self.adb.tap(POS_NEXT_PAGE.x, POS_NEXT_PAGE.y)
                time.sleep(0.30)

        return last_frame

    def get_sort_direction(self, frame: Image.Image) -> str:
        """Detects whether table is sorted ascending or descending."""
        top_white = sum(
            1
            for x in range(974, 982)
            for y in range(170, 174)
            if sum(frame.getpixel((x, y))) > 550
        )
        bot_white = sum(
            1
            for x in range(974, 982)
            for y in range(177, 181)
            if sum(frame.getpixel((x, y))) > 550
        )
        if bot_white >= 5:
            return "ascending"
        if top_white >= 5:
            return "descending"
        return "none"

    def ensure_price_sort_ascending(self) -> Optional[Image.Image]:
        """Ensures table is sorted by lowest unit price first (ascending)."""
        frame = self.capture_frame()
        if not frame:
            return None
        direction = self.get_sort_direction(frame)
        if direction == "ascending":
            return frame

        if self.use_adb and self.adb:
            self.adb.tap(POS_PRICE_HEADER.x, POS_PRICE_HEADER.y)
            for _ in range(8):
                time.sleep(0.15)
                frame = self.capture_frame()
                if not frame:
                    continue
                direction = self.get_sort_direction(frame)
                if direction != "none":
                    break

            if direction != "ascending":
                self.adb.tap(POS_PRICE_HEADER.x, POS_PRICE_HEADER.y)
                for _ in range(8):
                    time.sleep(0.15)
                    frame = self.capture_frame()
                    if not frame:
                        continue
                    direction = self.get_sort_direction(frame)
                    if direction == "ascending":
                        break

        return frame

    def run_query_collection(
        self,
        keyword: str,
        max_pages: int = 2,
        target_tab: str = "both",
    ) -> bool:
        """Executes full search and collection for an item with live quota check.

        Performs exactly 1 live screen quota check (>= 2 for both tabs, >= 1 for single tab).
        Returns True if collection succeeded, False if live quota is insufficient.

        Args:
            keyword: Item name.
            max_pages: Upper bound on pages to collect per tab.
            target_tab: 'both', 'asks', or 'trades'.

        Returns:
            True if collection succeeded, False if quota < required.
        """
        if not self.ensure_focus():
            return False

        # Single check per item: Check in-game quota directly from live screen
        req_total = 2 if target_tab == "both" else 1
        rem = self.get_screen_quota()
        if rem is not None:
            _logger.debug(
                f"[{self.current_instance}] Live screen quota: {rem}/500 remaining (need {req_total})."
            )
            if rem < req_total:
                _logger.warning(
                    f"[{self.current_instance}] Quota exhausted on screen ({rem} < {req_total})."
                )
                return False

        query_success = False

        # 1. Scrape Active Listings (查詢) if requested
        if target_tab in ("asks", "both"):
            self.switch_to_tab("query")
            if self.execute_search(keyword, reuse_existing=False):
                query_success = True
                verified_frame = self.ensure_price_sort_ascending()
                self.paginate_and_scrape(
                    max_pages=max_pages,
                    is_market=False,
                    initial_frame=verified_frame,
                    item_name=keyword,
                )

        # 2. Scrape Matched Trades (市價) if requested
        if target_tab in ("trades", "both"):
            self.switch_to_tab("market")
            reuse = target_tab == "both" and query_success
            if self.execute_search(keyword, reuse_existing=reuse):
                self.paginate_and_scrape(
                    max_pages=max_pages, is_market=True, item_name=keyword
                )
                try:
                    self.aggregator.aggregate_item(keyword, timeframe="1h")
                    self.aggregator.aggregate_item(keyword, timeframe="4h")
                    self.aggregator.aggregate_item(keyword, timeframe="1d")
                except Exception as err:
                    _logger.debug(f"Candle aggregation error for '{keyword}': {err}")

        try:
            update_item_timestamp(keyword)
        except Exception as err:
            _logger.debug(f"Timestamp update error for '{keyword}': {err}")

        return True

    def run_catalog_scan(
        self,
        keywords: List[str],
        max_pages_per_query: int = 2,
        target_tab: str = "both",
        start_index: int = 1,
    ) -> None:
        """Iterates over item catalog with live screen quota checks and auto-retry.

        Args:
            keywords: List of item names to collect.
            max_pages_per_query: Max pages per item per tab.
            target_tab: 'both', 'asks', or 'trades'.
            start_index: 1-based start index.
        """
        _logger.info(
            f"Starting catalog collection scan for {len(keywords)} items (Mode: '{target_tab}', Start: {start_index})..."
        )
        if not self.ensure_focus():
            _logger.error(f"Cannot focus '{self.current_instance}'. Halting scan.")
            return

        rem = self.get_screen_quota()
        if rem is not None:
            _logger.info(
                f"[{self.current_instance}] Auction House active. Live quota on screen: {rem}/500 remaining."
            )

        failed_items: List[str] = []
        for idx, item in enumerate(keywords, 1):
            if idx < start_index:
                continue

            if not self.is_auction_open():
                _logger.warning(
                    f"Auction House closed before [{idx}/{len(keywords)}] ('{item}'). Restoring..."
                )
                if not self.ensure_focus():
                    _logger.error("Failed to restore Auction House. Stopping run.")
                    break

            _logger.info(
                f"[{self.current_instance}] -> Scanning [{idx}/{len(keywords)}]: '{item}'"
            )
            try:
                ok = self.run_query_collection(
                    item, max_pages=max_pages_per_query, target_tab=target_tab
                )
                if not ok:
                    # Live screen quota < 2
                    rotated = False
                    if self.allow_instance_rotation:
                        req = 2 if target_tab == "both" else 1
                        rotated = self.rotate_to_next_available(required=req)
                        if rotated:
                            self.run_query_collection(
                                item,
                                max_pages=max_pages_per_query,
                                target_tab=target_tab,
                            )
                    if not rotated:
                        # All instances exhausted: safely exit and pause until 08:00 AM next day
                        self.leave_auction()
                        pause_until_next_8am(self.current_instance)
                        self.ensure_focus()
                        self.run_query_collection(
                            item,
                            max_pages=max_pages_per_query,
                            target_tab=target_tab,
                        )
            except Exception as err:
                _logger.error(f"Error processing item '{item}': {err}")
                failed_items.append(item)
            time.sleep(1.5)

        # Autonomous retry pass
        if failed_items and self.is_auction_open():
            _logger.info(
                f"Autonomous Retry Pass: Re-attempting {len(failed_items)} failed items."
            )
            for f_item in failed_items:
                try:
                    self.run_query_collection(
                        f_item,
                        max_pages=max_pages_per_query,
                        target_tab=target_tab,
                    )
                except Exception as err:
                    _logger.error(f"Retry failed for '{f_item}': {err}")
                time.sleep(2.0)

        _logger.info("Catalog collection scan completed.")
        try:
            self.leave_auction()
        except Exception:
            pass

    def shutdown(self) -> None:
        """Safely leaves Auction House and shuts down background workers."""
        try:
            self.leave_auction()
        except Exception as err:
            _logger.debug(f"Error leaving auction on shutdown: {err}")
        if hasattr(self, "ocr_worker"):
            self.ocr_worker.shutdown()
