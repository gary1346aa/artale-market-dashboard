import logging
import time
import os
from typing import List, Optional
from .window_manager import WindowManager
from .parser import MarketParser
from .database import init_db, save_active_listings, save_matched_trades
from .actions import human_click, human_delay, clear_and_paste, submit_existing_search
from .quota_manager import QuotaManager
from .aggregator import KlineAggregator
from .instance_launcher import InstanceLauncher
from .tier_evaluator import update_item_timestamp, TierEvaluator
from .async_ocr import AsyncOcrWorker

import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ArtaleCollector")

class MarketCollector:
    """
    Automates market scanning, tab navigation, OCR data collection, and DB persistence.
    Calibrated against Artale 1280x720 inner canvas (1024x576 reference coordinates).
    Supports multi-account rotation and automated instance launching into the Auction House.
    """
    POS_QUICK_SEARCH = (224, 32)      # Scaled to (280, 40) on 1280x720 (center of search box)
    POS_CONFIRM_INPUT = (948, 548)    # Scaled to (1185, 685) on 1280x720 - [確定] button
    POS_QUERY_TAB = (195, 72)         # Scaled to (244, 90) on 1280x720
    POS_MARKET_TAB = (417, 72)        # Scaled to (522, 90) on 1280x720
    POS_SIDEBAR_SEARCH = (223, 261)   # Scaled to (279, 327) on 1280x720
    POS_START_SEARCH = (250, 442)     # Scaled to (312, 553) on 1280x720
    POS_PRICE_HEADER = (756, 136)     # Scaled to (945, 170) on 1280x720 - [每個價錢]
    POS_NEXT_PAGE = (680, 112)        # Scaled to (850, 140) on 1280x720 - center of [>] button
    POS_FIRST_PAGE = (533, 112)       # Scaled to (666, 140) on 1280x720 - center of [|<] button

    def __init__(self, window_mgr: Optional[WindowManager] = None, instance_name: Optional[str] = None):
        self.quota_mgr = QuotaManager()
        self.launcher = InstanceLauncher()
        if instance_name:
            self.current_instance = instance_name
            self.quota_mgr.switch_instance(instance_name)
        else:
            self.current_instance = self.quota_mgr.get_available_instance() or "祈禱機"
        self.win_mgr = window_mgr or WindowManager(title_keywords=[self.current_instance, "LDPlayer", "雷電模擬器", "雷電"])
        self.aggregator = KlineAggregator()
        self.ocr_worker = AsyncOcrWorker()
        init_db()

    def switch_to_instance(self, instance_name: str) -> bool:
        """
        Switches the active tracker to a different LDPlayer instance.
        Ensures the target instance is booted and navigated into the Auction House.
        """
        logger.info(f"Switching active tracker to instance '{instance_name}'...")
        if not self.launcher.ensure_instance_in_auction(instance_name):
            logger.error(f"Failed to prepare '{instance_name}' in Auction House.")
            return False
        self.current_instance = instance_name
        self.win_mgr = WindowManager(title_keywords=[instance_name])
        self.quota_mgr.switch_instance(instance_name)
        self.ensure_focus()
        logger.info(f"Switched successfully to '{instance_name}'.")
        return True

    def ensure_focus(self) -> bool:
        if not self.win_mgr.find_window():
            logger.info(f"Window for '{self.current_instance}' not detected. Launching into auction...")
            if not self.launcher.ensure_instance_in_auction(self.current_instance):
                logger.error(f"Could not prepare instance '{self.current_instance}'.")
                return False

        # Bring window to front BEFORE capturing screen to prevent occlusion by File Explorer / CMD
        self.win_mgr.bring_to_front()
        time.sleep(0.8)

        if not self.is_auction_open():
            logger.info(f"Instance '{self.current_instance}' is open but not in Auction House. Navigating...")
            if not self.launcher.ensure_instance_in_auction(self.current_instance):
                logger.error(f"Could not navigate instance '{self.current_instance}' into Auction House.")
                return False
        return True

    def is_auction_open(self) -> bool:
        """
        Checks whether the Auction House modal is currently open.
        Guarantees that the bot NEVER interacts if the auction was closed.
        Uses robust multi-landmark scoring across invariant UI elements:
        1. White search box at top
        2. Bright green '開始搜尋' button in left sidebar
        3. Active cyan tab indicator ('查詢' or '市價')
        4. Dark gray exit button '離開' at top right
        """
        frame = self.win_mgr.capture_frame()
        if not frame or frame.width < 500 or frame.height < 300:
            return False
        try:
            # Landmark 1: White search box
            box_ok = any(frame.getpixel((x, 48))[0] > 180 and frame.getpixel((x, 48))[1] > 180 for x in (240, 280, 320))

            # Landmark 2: Green '開始搜尋' button (dominant green in sidebar button region)
            green_ok = any(frame.getpixel((x, y))[1] > 110 and frame.getpixel((x, y))[1] > frame.getpixel((x, y))[2] + 35 
                           for x in (290, 312, 335) for y in (540, 546, 552))

            # Landmark 3: Active cyan tab ('查詢' x ~ 200 or '市價' x ~ 400 at y ~ 120)
            cyan_ok = any(frame.getpixel((x, 120))[1] > 80 and frame.getpixel((x, 120))[2] > 80 and frame.getpixel((x, 120))[0] < 80
                          for x in (180, 220, 260, 360, 400, 440))

            # Landmark 4: Dark top exit button / top bar border
            top_ok = any(frame.getpixel((x, 48))[0] < 60 and frame.getpixel((x, 48))[1] < 60 for x in (780, 790, 800))

            score = sum([box_ok, green_ok, cyan_ok, top_ok])
            return score >= 2
        except Exception as e:
            logger.error(f"Error in is_auction_open: {e}")
            return False

    def click_ref(self, ref_x: int, ref_y: int):
        if not self.is_auction_open():
            logger.error("SAFETY GUARD: Auction House is closed! Refusing to click.")
            return
        screen_pt = self.win_mgr.to_screen_coords(ref_x, ref_y)
        if screen_pt:
            human_click(screen_pt[0], screen_pt[1])
        else:
            logger.warning(f"Failed to map ref coordinates ({ref_x}, {ref_y}) to screen space.")

    def switch_to_tab(self, target_tab: str) -> bool:
        """
        Switches to 'query' (查詢) or 'market' (市價) tab.
        """
        if target_tab == "query":
            logger.info("Switching to [查詢] (Active Listings) tab...")
            self.click_ref(*self.POS_QUERY_TAB)
        else:
            logger.info("Switching to [市價] (Market Trades) tab...")
            self.click_ref(*self.POS_MARKET_TAB)
            
        human_delay(1.0, 1.5)
        return True

    def execute_search(self, keyword: str, reuse_existing: bool = False) -> bool:
        """
        Inputs keyword into the quick search box and submits via Enter cleanly.
        If reuse_existing is True, skips Alt+8 and clipboard sync, directly submitting
        the keyword already present in the search bar.
        """
        if not self.is_auction_open():
            logger.error("SAFETY GUARD: Auction House is closed! Refusing to search.")
            return False

        search_pt = self.win_mgr.to_screen_coords(*self.POS_QUICK_SEARCH)
        confirm_pt = self.win_mgr.to_screen_coords(*self.POS_CONFIRM_INPUT)
        if not search_pt:
            return False

        if reuse_existing:
            logger.info(f"Reusing search bar keyword: '{keyword}' (fast submit)")
            submit_existing_search(search_pt[0], search_pt[1], confirm_pt=confirm_pt)
        else:
            logger.info(f"Searching for item: '{keyword}'")
            clear_and_paste(search_pt[0], search_pt[1], keyword, confirm_pt=confirm_pt, win_mgr=self.win_mgr)

        human_delay(1.0, 1.5)
        return True

    def scrape_current_page(self) -> dict:
        """
        Captures the screen, parses the current page, and saves records directly to DB.
        Returns extracted records, tab, pagination, and a page signature for duplicate detection.
        """
        frame = self.win_mgr.capture_frame()
        if not frame:
            logger.warning("Frame capture returned empty.")
            return {"tab": "unknown", "count": 0, "signature": None}

        # Save last captured frame for verification
        try:
            os.makedirs("data", exist_ok=True)
            frame.save("data/last_captured_frame.png")
        except Exception:
            pass

        parser = MarketParser(frame)
        res = parser.parse()
        tab = res["tab"]
        records = res["records"]

        if tab == "market":
            save_matched_trades(records)
            logger.info(f"[市價] Captured {len(records)} completed trades from page.")
            signature = tuple((r.item_name, r.matched_unit_price, r.trade_time) for r in records)
        else:
            save_active_listings(records)
            logger.info(f"[查詢] Captured {len(records)} active listings from page.")
            signature = tuple((r.item_name, r.unit_price, r.total_price) for r in records)

        return {
            "tab": tab,
            "quota": res["quota"],
            "pagination": res["pagination"],
            "count": len(records),
            "signature": signature if records else None
        }

    def paginate_and_scrape(self, max_pages: int = 3, is_market: bool = False):
        """
        Scrapes current tab across pages using pipelined asynchronous OCR.
        Fast Micro-OCR path: Reads (curr_p, total_p) on Page 1 in ~15ms, then streams
        all remaining pages 2..N rapidly to the background OCR queue.
        Falls back to synchronous page-by-page verification if Page 1 pagination is unread.
        """
        effective_max = 50 if is_market else max_pages
        tab = "market" if is_market else "query"
        self.ocr_worker.reset_signature()

        # 1. Capture Page 1 frame
        frame1 = self.win_mgr.capture_frame()
        if not frame1:
            logger.warning("Frame capture returned empty on page 1.")
            return

        # Save last captured frame for verification
        try:
            os.makedirs("data", exist_ok=True)
            frame1.save("data/last_captured_frame.png")
        except Exception:
            pass

        # 2. Fast Micro-OCR on pagination control
        parser1 = MarketParser(frame1)
        pagination = parser1.parse_pagination()

        if pagination:
            curr_p, total_p = pagination
            target_pages = min(total_p, effective_max)
            logger.info(f"Page 1 Micro-OCR: Detected page {curr_p}/{total_p}. Target to collect: {target_pages} pages.")

            # Queue Page 1 for background full OCR & DB persistence
            self.ocr_worker.submit(frame1, tab=tab, page_num=1)

            # If only 1 page, wait for worker completion and return immediately
            if target_pages <= 1:
                logger.info(f"Single page result ({curr_p}/{total_p}). Stopping pagination.")
                self.ocr_worker.wait_all()
                return

            # Rapidly flip and stream pages 2 through target_pages
            for page_idx in range(2, target_pages + 1):
                next_pt = self.win_mgr.to_screen_coords(*self.POS_NEXT_PAGE)
                if not next_pt:
                    logger.warning("Failed to map next page coordinates.")
                    break

                logger.info(f"Flipping to page {page_idx}/{target_pages}...")
                human_click(next_pt[0], next_pt[1])
                human_delay(0.45, 0.55)

                frame = self.win_mgr.capture_frame()
                if not frame:
                    logger.warning(f"Frame capture returned empty on page {page_idx}.")
                    break

                self.ocr_worker.submit(frame, tab=tab, page_num=page_idx)

            # Sync barrier: Ensure all queued pages are completely parsed and saved to DB
            self.ocr_worker.wait_all()

        else:
            # Fallback: Pagination indicator unparsed on Page 1 (e.g. empty results or font anomaly)
            logger.info("Pagination unparsed on Page 1. Running safe fallback loop...")
            self._fallback_paginate_and_scrape(max_pages=max_pages, is_market=is_market)

    def _fallback_paginate_and_scrape(self, max_pages: int = 3, is_market: bool = False):
        """
        Synchronous fallback pagination loop when Page 1 pagination indicator cannot be read.
        """
        effective_max = 50 if is_market else max_pages
        last_page_sig = None

        for page_idx in range(1, effective_max + 1):
            info = self.scrape_current_page()
            pagination = info.get("pagination")
            count = info.get("count", 0)
            sig = info.get("signature")

            # 1. Empty page detection beyond page 1
            if count == 0 and page_idx > 1:
                logger.info(f"Page {page_idx} is empty. Reached end of listings.")
                break

            # 2. Duplicate page detection
            if last_page_sig is not None and sig is not None and sig == last_page_sig:
                logger.info(f"Page {page_idx} records are identical to previous page. Reached final page.")
                break
            last_page_sig = sig

            # 3. Pagination indicator check (curr_p >= total_p)
            if pagination:
                curr_p, total_p = pagination
                logger.info(f"Scraped page {curr_p} of {total_p} ({count} items)")
                if curr_p >= total_p:
                    logger.info(f"Reached final page ({curr_p}/{total_p}). Stopping pagination.")
                    break
            else:
                runaway_limit = max_pages if not is_market else 5
                if page_idx >= runaway_limit:
                    logger.warning(f"Pagination unknown and reached safe limit ({runaway_limit} pages). Stopping.")
                    break

            if page_idx >= effective_max:
                break

            next_pt = self.win_mgr.to_screen_coords(*self.POS_NEXT_PAGE)
            if next_pt:
                logger.info("Clicking next page button...")
                human_click(next_pt[0], next_pt[1])
            else:
                logger.warning("Failed to map next page coordinates.")
                break
            human_delay(0.45, 0.55)

    def get_sort_direction(self, frame) -> str:
        """
        Determines if table is sorted ascending (lowest price first) or descending (highest price first).
        Top arrow lit = descending; bottom arrow lit = ascending.
        """
        top_white = sum(1 for x in range(974, 982) for y in range(170, 174) if sum(frame.getpixel((x, y))) > 550)
        bot_white = sum(1 for x in range(974, 982) for y in range(177, 181) if sum(frame.getpixel((x, y))) > 550)
        if bot_white >= 5:
            return "ascending"
        elif top_white >= 5:
            return "descending"
        return "none"

    def ensure_price_sort_ascending(self):
        """
        Ensures the table is sorted by lowest unit price first (ascending).
        If not sorted or descending, clicks '每個價錢' header until the down arrow (ascending) lights up.
        """
        frame = self.win_mgr.capture_frame()
        if not frame:
            return
        direction = self.get_sort_direction(frame)
        logger.info(f"Current sort direction on table: '{direction}'")
        if direction == "ascending":
            return

        # Click header once
        logger.info("Clicking [每個價錢] header to sort by price...")
        self.click_ref(*self.POS_PRICE_HEADER)
        human_delay(1.0, 1.5)

        frame = self.win_mgr.capture_frame()
        direction = self.get_sort_direction(frame)
        logger.info(f"Sort direction after click 1: '{direction}'")
        if direction != "ascending":
            logger.info("Toggling [每個價錢] header to ensure ASCENDING order (lowest price first)...")
            self.click_ref(*self.POS_PRICE_HEADER)
            human_delay(1.0, 1.5)

    def run_query_collection(self, keyword: str, max_pages: int = 2, target_tab: str = "both"):
        """
        Performs search for a keyword, ensures price sort is ascending, and collects requested tabs.
        target_tab: 'asks' (only 查詢), 'trades' (only 市價), or 'both'
        """
        # Check & auto-rotate instance if current instance quota is exhausted
        active_inst = self.quota_mgr.get_available_instance(required=1)
        if not active_inst:
            logger.warning("DAILY QUOTA EXHAUSTED across all instances. Pausing until 08:00 AM reset.")
            return

        if active_inst != self.current_instance:
            if not self.switch_to_instance(active_inst):
                logger.error(f"Failed to switch to instance '{active_inst}'.")
                return

        if not self.ensure_focus():
            return
        if not self.is_auction_open():
            logger.error("SAFETY GUARD: Auction House is closed! Halting immediately.")
            return

        query_success = False

        # 1. Scrape Active Listings (查詢) if requested
        if target_tab in ("asks", "both"):
            if not self.quota_mgr.can_search(self.current_instance, required=1):
                logger.warning(f"Quota for '{self.current_instance}' exhausted. Checking other instances...")
                alt_inst = self.quota_mgr.get_available_instance(required=1)
                if alt_inst and alt_inst != self.current_instance:
                    self.switch_to_instance(alt_inst)
                else:
                    return
            self.switch_to_tab("query")
            if self.execute_search(keyword, reuse_existing=False):
                query_success = True
                self.quota_mgr.record_search(self.current_instance, count=1)
                self.ensure_price_sort_ascending()
                self.paginate_and_scrape(max_pages=max_pages, is_market=False)

        # 2. Scrape Matched Trades (市價) if requested
        if target_tab in ("trades", "both"):
            if not self.quota_mgr.can_search(self.current_instance, required=1):
                logger.warning(f"Quota for '{self.current_instance}' exhausted. Checking other instances...")
                alt_inst = self.quota_mgr.get_available_instance(required=1)
                if alt_inst and alt_inst != self.current_instance:
                    self.switch_to_instance(alt_inst)
                    query_success = False
                else:
                    return
            self.switch_to_tab("market")
            reuse = (target_tab == "both" and query_success)
            if self.execute_search(keyword, reuse_existing=reuse):
                self.quota_mgr.record_search(self.current_instance, count=1)
                # Keep default sort (sorted by match date descending) and collect ALL pages
                self.paginate_and_scrape(max_pages=max_pages, is_market=True)
                # Auto-generate K-line candles for this item
                try:
                    self.aggregator.aggregate_item(keyword, timeframe="1h")
                    self.aggregator.aggregate_item(keyword, timeframe="4h")
                    self.aggregator.aggregate_item(keyword, timeframe="1d")
                except Exception:
                    pass

        # Update last_updated timestamp for this item in items_watchlist.json
        try:
            update_item_timestamp(keyword)
        except Exception:
            pass

    def run_catalog_scan(self, keywords: List[str], max_pages_per_query: int = 2, target_tab: str = "both", start_index: int = 1):
        """
        Iterates over a list of items and captures market data with multi-instance quota tracking and auto-retry.
        """
        logger.info(f"Starting catalog collection scan for {len(keywords)} items (Target Mode: '{target_tab}', Start Index: {start_index})...")
        if not self.ensure_focus():
            logger.error(f"Cannot initialize or focus instance '{self.current_instance}'. Halting scan.")
            return

        quota = self.quota_mgr.get_status()
        logger.info(
            f"Multi-Instance Quota: {quota['total_consumed']} / {quota['total_capacity']} used "
            f"({quota['total_remaining']} remaining across {len(quota['instances'])} instances). "
            f"Active: '{self.current_instance}'"
        )

        failed_items = []
        for idx, item in enumerate(keywords, 1):
            if idx < start_index:
                continue
            if not self.is_auction_open():
                logger.warning(f"Auction House was not open before item [{idx}/{len(keywords)}] ('{item}'). Restoring...")
                if not self.ensure_focus():
                    logger.error("SAFETY GUARD: Failed to restore Auction House! Stopping run.")
                    break
            logger.info(f"--- Processing [{idx}/{len(keywords)}]: '{item}' [Using: {self.current_instance}] ---")
            try:
                self.run_query_collection(item, max_pages=max_pages_per_query, target_tab=target_tab)
            except Exception as e:
                logger.error(f"Error processing item '{item}': {e}")
                failed_items.append(item)
            human_delay(1.5, 2.5)

        # Autonomous Retry Pass: Zero human intervention needed
        if failed_items and self.is_auction_open():
            logger.info(f"=== Autonomous Retry Pass: Re-attempting {len(failed_items)} failed items ===")
            for f_item in failed_items:
                try:
                    self.run_query_collection(f_item, max_pages=max_pages_per_query, target_tab=target_tab)
                except Exception as e:
                    logger.error(f"Retry failed for '{f_item}': {e}")
                human_delay(2.0, 3.0)

        logger.info("Catalog collection scan completed.")

        # Autonomous Tier Evaluation Pass
        try:
            evaluator = TierEvaluator()
            evaluator.evaluate_and_update_watchlist()
        except Exception as e:
            logger.debug(f"Tier re-evaluation error: {e}")

    def shutdown(self):
        """
        Shuts down background OCR workers cleanly.
        """
        if hasattr(self, "ocr_worker"):
            self.ocr_worker.shutdown()


