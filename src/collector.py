import logging
import time
import os
from typing import List, Optional
from .window_manager import WindowManager
from .parser import MarketParser
from .database import init_db, save_active_listings, save_matched_trades
from .actions import human_click, human_delay, clear_and_paste, submit_existing_search
from .quota_manager import read_quota_from_frame, pause_until_next_8am
from .aggregator import KlineAggregator
from .instance_launcher import InstanceLauncher
from .tier_evaluator import update_item_timestamp, TierEvaluator
from .async_ocr import AsyncOcrWorker
from .adb_controller import AdbController
from .dataset_logger import save_dataset_frame

def _discover_instances() -> Dict[str, str]:
    mapping = {
        "祈禱機": "emulator-5558",
        "槍手": "emulator-5560",
        "打火機": "emulator-5562",
        "弩手": "emulator-5568",
    }
    try:
        import subprocess
        p = subprocess.run([r"C:\LDPlayer\LDPlayer9\ldconsole.exe", "list2"], capture_output=True, timeout=2)
        if p.returncode == 0:
            for line in p.stdout.decode('utf-8', errors='ignore').splitlines():
                parts = line.strip().split(',')
                if len(parts) >= 2:
                    idx, name = parts[0], parts[1]
                    port = 5554 + int(idx) * 2
                    mapping[name] = f"emulator-{port}"
    except Exception:
        pass
    return mapping

INSTANCE_TO_DEVICE = _discover_instances()

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

    def __init__(self, window_mgr: Optional[WindowManager] = None, instance_name: Optional[str] = None, use_adb: bool = True, allow_instance_rotation: bool = True):
        self.use_adb = use_adb
        self.allow_instance_rotation = allow_instance_rotation
        self.launcher = InstanceLauncher()
        self.current_instance = instance_name or "槍手"
        self.win_mgr = window_mgr or WindowManager(title_keywords=[self.current_instance, "LDPlayer", "雷電模擬器", "雷電"])
        self.aggregator = KlineAggregator()
        self.ocr_worker = AsyncOcrWorker()

        if self.use_adb:
            attached = AdbController.list_attached_devices()
            rev_map = {v: k for k, v in INSTANCE_TO_DEVICE.items()}
            dev_id = INSTANCE_TO_DEVICE.get(self.current_instance)
            if (not instance_name or dev_id not in attached) and attached:
                dev_id = attached[0]
                self.current_instance = rev_map.get(dev_id, dev_id)
            elif not dev_id:
                dev_id = attached[0] if attached else "emulator-5560"
            self.adb = AdbController(device_id=dev_id)
            logger.info(f"Initialized ADB background engine on device '{dev_id}' for '{self.current_instance}'.")
        else:
            self.adb = None

        init_db()

    def capture_frame(self) -> Optional[Image.Image]:
        if self.use_adb and self.adb:
            return self.adb.screencap()
        return self.win_mgr.capture_frame() if self.win_mgr else None

    def switch_to_instance(self, instance_name: str) -> bool:
        """
        Switches the active tracker to a different LDPlayer instance.
        Ensures the target instance is booted and navigated into the Auction House.
        """
        logger.info(f"Switching active tracker to instance '{instance_name}'...")
        self.current_instance = instance_name

        if self.use_adb and self.adb:
            dev_id = INSTANCE_TO_DEVICE.get(instance_name, "emulator-5558")
            self.adb = AdbController(device_id=dev_id)
            logger.info(f"Switched ADB device to '{dev_id}' ({instance_name}).")
        else:
            self.win_mgr = WindowManager(title_keywords=[instance_name])

        self.ensure_focus()
        logger.info(f"Switched successfully to '{instance_name}'.")
        return True

    def get_screen_quota(self, frame=None) -> Optional[int]:
        """
        Directly reads in-game quota header '搜尋次數 XXX/500' from live screen frame.
        Uses 100% deterministic Digit Engine (parse_quota_header). Zero state maintained.
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

    def sync_quota_from_frame(self, frame=None) -> Optional[int]:
        """Reads in-game quota header directly from screen. Zero state maintained."""
        return self.get_screen_quota(frame)

    def rotate_to_next_available(self, required: int = 2) -> bool:
        """
        Rotates to the next online attached LDPlayer instance and checks its live screen quota.
        """
        if not self.use_adb:
            return False
        attached = AdbController.list_attached_devices()
        candidates = [name for name, dev in INSTANCE_TO_DEVICE.items() if dev in attached and name != self.current_instance]
        for name in candidates:
            logger.info(f"Checking alternative candidate instance '{name}'...")
            if not self.switch_to_instance(name):
                continue
            rem = self.get_screen_quota()
            if rem is not None and rem >= required:
                logger.info(f"Switched to '{name}' with {rem}/500 live screen quota.")
                return True
            else:
                logger.warning(f"Candidate '{name}' has insufficient screen quota ({rem}/500).")
        return False

    def ensure_focus(self, max_retries: int = 3) -> bool:
        if self.use_adb and self.adb:
            for attempt in range(1, max_retries + 1):
                if self.adb.is_auction_open():
                    rem = self.get_screen_quota()
                    if rem is not None:
                        logger.info(f"[{self.current_instance}] Auction House ready (Live screen quota: {rem}/500).")
                    return True

                logger.info(f"Instance '{self.current_instance}' ({self.adb.device_id}) opening Auction House (attempt {attempt}/{max_retries})...")
                if self.adb.enter_auction_from_free_market(max_wait_sec=8):
                    logger.info(f"Successfully entered Auction House on '{self.current_instance}'.")
                    rem = self.get_screen_quota()
                    if rem is not None:
                        logger.info(f"[{self.current_instance}] Live screen quota: {rem}/500.")
                    return True

                if attempt < max_retries:
                    time.sleep(2.0)

            logger.warning(f"Instance '{self.current_instance}' ({self.adb.device_id}) failed to enter Auction House after {max_retries} attempts.")
            return False

        if not self.win_mgr.find_window():
            logger.info(f"Window for '{self.current_instance}' not detected. Launching into auction...")
            if not self.launcher.ensure_instance_in_auction(self.current_instance):
                logger.error(f"Could not prepare instance '{self.current_instance}'.")
                return False

        self.win_mgr.bring_to_front()
        time.sleep(0.8)

        if not self.is_auction_open():
            logger.info(f"Instance '{self.current_instance}' is open but not in Auction House. Navigating...")
            if not self.launcher.ensure_instance_in_auction(self.current_instance):
                logger.error(f"Could not navigate instance '{self.current_instance}' into Auction House.")
                return False
        self.sync_quota_from_frame()
        return True

    def leave_auction(self) -> bool:
        """
        Safely exits the Auction House to the Free Market to prevent idle timeout.
        """
        if self.use_adb and self.adb:
            return self.adb.leave_auction_to_free_market()
        return True

    def is_auction_open(self) -> bool:
        """
        Checks whether the Auction House modal is currently open.
        """
        if self.use_adb and self.adb:
            return self.adb.is_auction_open()

        frame = self.capture_frame()
        if not frame or frame.width < 500 or frame.height < 300:
            return False
        try:
            # 1. Minimap check: In Free Market / World, minimap at (30, 18) is bright white (> 200, > 200, > 200)
            p_mm = frame.getpixel((30, 18))[:3]
            if p_mm[0] > 200 and p_mm[1] > 200 and p_mm[2] > 200:
                return False

            # 2. Sidebar green '開始搜尋' button: x in 280..340, y in 535..558
            green_count = sum(1 for x in range(280, 340, 5) for y in range(535, 558, 3) 
                              if frame.getpixel((x, y))[1] > 130 and frame.getpixel((x, y))[0] > 100 
                              and frame.getpixel((x, y))[2] < 70 and frame.getpixel((x, y))[1] > frame.getpixel((x, y))[0] + 15)
            green_ok = green_count >= 5

            # 3. Top-right '離開' button dark container with white text
            p_leave_bg = frame.getpixel((975, 40))[:3]
            bg_ok = (20 <= p_leave_bg[0] <= 55 and 20 <= p_leave_bg[1] <= 55 and 20 <= p_leave_bg[2] <= 55)
            text_count = sum(1 for x in range(990, 1040, 3) for y in range(32, 48, 2)
                             if all(c > 170 for c in frame.getpixel((x, y))[:3]))
            leave_ok = bg_ok and text_count >= 4

            # 4. Auction house header tab area (100, 120) dark frame
            p_hdr = frame.getpixel((100, 120))[:3]
            hdr_ok = (p_hdr[0] < 70 and p_hdr[1] < 70 and p_hdr[2] < 70)

            return sum([green_ok, leave_ok, hdr_ok]) >= 2
        except Exception as e:
            logger.error(f"Error in is_auction_open: {e}")
            return False

    def click_ref(self, ref_x: int, ref_y: int):
        if not self.is_auction_open():
            logger.error("SAFETY GUARD: Auction House is closed! Refusing to click.")
            return
        if self.use_adb and self.adb:
            cx = int(ref_x * 1.25)
            cy = int(ref_y * 1.25)
            self.adb.tap(cx, cy)
        else:
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
            self.click_ref(*self.POS_QUERY_TAB)
        else:
            self.click_ref(*self.POS_MARKET_TAB)
            
        if self.use_adb and self.adb:
            time.sleep(0.6)
        else:
            human_delay(1.0, 1.5)
        return True

    def execute_search(self, keyword: str, reuse_existing: bool = False) -> bool:
        """
        Inputs keyword into the quick search box and submits via Enter cleanly.
        If reuse_existing is True, skips typing and reuses existing search term.
        """
        if not self.is_auction_open():
            logger.error("SAFETY GUARD: Auction House is closed! Refusing to search.")
            return False

        if self.use_adb and self.adb:
            if reuse_existing:
                logger.debug(f"Reusing search bar keyword via ADB: '{keyword}' (fast submit)")
                self.adb.tap(*self.adb.POS_QUICK_SEARCH)
                time.sleep(0.2)
                self.adb.press_enter()
                time.sleep(0.4)
                self.adb.handle_lingering_popups()
            else:
                logger.info(f"Searching for item via ADB: '{keyword}'")
                self.adb.tap(*self.adb.POS_QUICK_SEARCH)
                time.sleep(0.25)
                self.adb.input_chinese(keyword)
                time.sleep(0.15)
                self.adb.press_enter()
                time.sleep(0.4)
                self.adb.handle_lingering_popups()
            time.sleep(0.2)
            return True

        search_pt = self.win_mgr.to_screen_coords(*self.POS_QUICK_SEARCH)
        confirm_pt = self.win_mgr.to_screen_coords(*self.POS_CONFIRM_INPUT)
        if not search_pt:
            return False

        if reuse_existing:
            logger.debug(f"Reusing search bar keyword: '{keyword}' (fast submit)")
            submit_existing_search(search_pt[0], search_pt[1], confirm_pt=confirm_pt)
        else:
            logger.info(f"Searching for item: '{keyword}'")
            clear_and_paste(search_pt[0], search_pt[1], keyword, confirm_pt=confirm_pt, win_mgr=self.win_mgr)

        human_delay(1.0, 1.5)
        return True

    def scrape_current_page(self, item_name: Optional[str] = None) -> dict:
        """
        Captures the screen, parses the current page, and saves records directly to DB.
        Returns extracted records, tab, pagination, and a page signature for duplicate detection.
        """
        frame = self.capture_frame()
        if not frame:
            logger.warning("Frame capture returned empty.")
            return {"tab": "unknown", "count": 0, "signature": None}

        if self.use_adb:
            try:
                os.makedirs("data", exist_ok=True)
                frame.save("data/last_captured_frame.jpg", format="JPEG", quality=85)
            except Exception:
                pass

        parser = MarketParser(frame, item_name=item_name)
        res = parser.parse()
        tab = res["tab"]
        records = res["records"]
        save_dataset_frame(frame, item_name=item_name, tab=tab, page_num=1, device_id=self.adb.device_id if self.adb else None)

        try:
            if tab == "market":
                save_matched_trades(records)
                logger.debug(f"[市價] Captured {len(records)} completed trades from page.")
                signature = tuple((r.item_name, r.matched_unit_price, r.trade_time) for r in records)
            else:
                save_active_listings(records)
                logger.debug(f"[查詢] Captured {len(records)} active listings from page.")
                signature = tuple((r.item_name, r.unit_price, r.total_price) for r in records)
        except Exception as e:
            import datetime
            err_dir = os.path.join("scratch", "debug_errors")
            os.makedirs(err_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c for c in (item_name or "unknown") if c.isalnum() or c in ("-", "_"))
            err_path = os.path.join(err_dir, f"err_{safe_name}_{tab}_{ts}.png")
            try:
                frame.save(err_path)
                logger.error(f"[Collector] Saved failed frame to: {os.path.abspath(err_path)}")
            except Exception:
                pass
            raise

        return {
            "tab": tab,
            "quota": res["quota"],
            "pagination": res["pagination"],
            "count": len(records),
            "signature": signature if records else None,
            "frame": frame
        }

    def paginate_and_scrape(self, max_pages: int = 3, is_market: bool = False, initial_frame: Optional[Image.Image] = None, item_name: Optional[str] = None) -> Optional[Image.Image]:
        """
        Scrapes current tab across pages using pipelined asynchronous OCR.
        Fast Micro-OCR path: Reads (curr_p, total_p) on Page 1 in ~15ms, then streams
        all remaining pages 2..N rapidly to the background OCR queue.
        Falls back to synchronous page-by-page verification if Page 1 pagination is unread.
        Returns the final captured frame of the tab.
        """
        effective_max = 50 if is_market else max_pages
        tab = "market" if is_market else "query"
        self.ocr_worker.reset_signature()

        # 1. Capture Page 1 frame (or reuse confirmed frame from sort verification)
        frame1 = initial_frame if initial_frame is not None else self.capture_frame()
        if not frame1:
            logger.warning("Frame capture returned empty on page 1.")
            return None

        # 2. Fast Micro-OCR on pagination control
        parser1 = MarketParser(frame1, item_name=item_name)
        pagination = parser1.parse_pagination()

        # Resilient retry: if initial frame was captured during server network response transition
        if not pagination:
            time.sleep(0.35)
            fresh = self.capture_frame()
            if fresh:
                frame1 = fresh
                parser1 = MarketParser(frame1, item_name=item_name)
                pagination = parser1.parse_pagination()

        try:
            os.makedirs("data", exist_ok=True)
            frame1.save("data/last_captured_frame.jpg", format="JPEG", quality=85)
        except Exception:
            pass

        last_frame = frame1

        if pagination:
            curr_p, total_p = pagination
            target_pages = min(total_p, effective_max)
            logger.debug(f"Page 1 Micro-OCR: Detected page {curr_p}/{total_p}. Target to collect: {target_pages} pages.")

            # Queue Page 1 for background full OCR & DB persistence
            self.ocr_worker.submit(frame1, tab=tab, page_num=1, item_name=item_name, device_id=self.adb.device_id if self.adb else None)

            if target_pages > 1:
                # Rapidly flip and stream pages 2 through target_pages (validated 300ms delay)
                for page_idx in range(2, target_pages + 1):
                    if self.use_adb and self.adb:
                        self.adb.tap(*self.adb.POS_NEXT_PAGE)
                        time.sleep(0.30)
                    else:
                        next_pt = self.win_mgr.to_screen_coords(*self.POS_NEXT_PAGE)
                        if not next_pt:
                            logger.warning("Failed to map next page coordinates.")
                            break
                        human_click(next_pt[0], next_pt[1])
                        human_delay(0.35, 0.45)

                    frame = self.capture_frame()
                    if not frame:
                        logger.warning(f"Frame capture returned empty on page {page_idx}.")
                        break

                    last_frame = frame
                    self.ocr_worker.submit(frame, tab=tab, page_num=page_idx, item_name=item_name, device_id=self.adb.device_id if self.adb else None)
            else:
                logger.debug(f"Single page result ({curr_p}/{total_p}). Stopping pagination.")

            self.ocr_worker.wait_all()
            return last_frame

        else:
            logger.debug("Pagination unparsed on Page 1. Running safe fallback loop...")
            return self._fallback_paginate_and_scrape(max_pages=max_pages, is_market=is_market, item_name=item_name)

    def _fallback_paginate_and_scrape(self, max_pages: int = 3, is_market: bool = False, item_name: Optional[str] = None) -> Optional[Image.Image]:
        """
        Synchronous fallback pagination loop when Page 1 pagination indicator cannot be read.
        Returns the final captured frame of the tab.
        """
        effective_max = 50 if is_market else max_pages
        last_page_sig = None
        last_frame = None

        for page_idx in range(1, effective_max + 1):
            info = self.scrape_current_page(item_name=item_name)
            last_frame = info.get("frame")
            pagination = info.get("pagination")
            count = info.get("count", 0)
            sig = info.get("signature")

            if count == 0 and page_idx > 1:
                logger.debug(f"Page {page_idx} is empty. Reached end of listings.")
                break

            if last_page_sig is not None and sig is not None and sig == last_page_sig:
                logger.debug(f"Page {page_idx} records are identical to previous page. Reached final page.")
                break
            last_page_sig = sig

            if pagination:
                curr_p, total_p = pagination
                logger.debug(f"Scraped page {curr_p} of {total_p} ({count} items)")
                if curr_p >= total_p:
                    logger.debug(f"Reached final page ({curr_p}/{total_p}). Stopping pagination.")
                    break
            else:
                runaway_limit = max_pages if not is_market else 5
                if page_idx >= runaway_limit:
                    logger.warning(f"Pagination unknown and reached safe limit ({runaway_limit} pages). Stopping.")
                    break

            if page_idx >= effective_max:
                break

            if self.use_adb and self.adb:
                self.adb.tap(*self.adb.POS_NEXT_PAGE)
                time.sleep(0.30)
            else:
                next_pt = self.win_mgr.to_screen_coords(*self.POS_NEXT_PAGE)
                if next_pt:
                    human_click(next_pt[0], next_pt[1])
                    human_delay(0.35, 0.45)
                else:
                    logger.warning("Failed to map next page coordinates.")
                    break

        return last_frame

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

    def ensure_price_sort_ascending(self) -> Optional[Image.Image]:
        """
        Ensures the table is sorted by lowest unit price first (ascending).
        Returns the confirmed ascending screen frame (or None) for zero-latency reuse in pagination.
        """
        frame = self.capture_frame()
        if not frame:
            return None
        direction = self.get_sort_direction(frame)
        logger.debug(f"Current sort direction on table: '{direction}'")
        if direction == "ascending":
            return frame

        logger.debug("Clicking [每個價錢] header to sort by price...")
        self.click_ref(*self.POS_PRICE_HEADER)

        frame = None
        direction = "none"
        for _ in range(8):
            time.sleep(0.15)
            frame = self.capture_frame()
            if not frame:
                continue
            direction = self.get_sort_direction(frame)
            if direction != "none":
                break

        logger.debug(f"Sort direction after click 1: '{direction}'")
        if direction != "ascending":
            logger.debug("Toggling [每個價錢] header to ensure ASCENDING order (lowest price first)...")
            self.click_ref(*self.POS_PRICE_HEADER)
            for _ in range(8):
                time.sleep(0.15)
                frame = self.capture_frame()
                if not frame:
                    continue
                direction = self.get_sort_direction(frame)
                if direction == "ascending":
                    break

        return frame

    def run_query_collection(self, keyword: str, max_pages: int = 2, target_tab: str = "both") -> bool:
        """
        Performs search for a keyword, ensures price sort is ascending, and collects requested tabs.
        target_tab: 'asks' (only 查詢), 'trades' (only 市價), or 'both'
        Returns True if search succeeded, False if quota on screen is insufficient (< 2).
        """
        if not self.ensure_focus():
            return False

        # Single check per item: Check in-game quota directly from live screen
        req_total = 2 if target_tab == "both" else 1
        rem = self.get_screen_quota()
        if rem is not None:
            logger.info(f"[{self.current_instance}] Live screen quota: {rem}/500 remaining (need {req_total}).")
            if rem < req_total:
                logger.warning(f"[{self.current_instance}] Quota exhausted on screen ({rem} < {req_total}).")
                return False

        query_success = False

        # 1. Scrape Active Listings (查詢) if requested
        if target_tab in ("asks", "both"):
            self.switch_to_tab("query")
            if self.execute_search(keyword, reuse_existing=False):
                query_success = True
                verified_frame = self.ensure_price_sort_ascending()
                self.paginate_and_scrape(max_pages=max_pages, is_market=False, initial_frame=verified_frame, item_name=keyword)

        # 2. Scrape Matched Trades (市價) if requested
        if target_tab in ("trades", "both"):
            self.switch_to_tab("market")
            reuse = (target_tab == "both" and query_success)
            if self.execute_search(keyword, reuse_existing=reuse):
                self.paginate_and_scrape(max_pages=max_pages, is_market=True, item_name=keyword)
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

        return True

    def run_catalog_scan(self, keywords: List[str], max_pages_per_query: int = 2, target_tab: str = "both", start_index: int = 1, max_pages: Optional[int] = None):
        """
        Iterates over a list of items and captures market data with live screen quota checks and auto-retry.
        """
        pages = max_pages if max_pages is not None else max_pages_per_query
        logger.info(f"Starting catalog collection scan for {len(keywords)} items (Target Mode: '{target_tab}', Start Index: {start_index})...")
        if not self.ensure_focus():
            logger.error(f"Cannot initialize or focus instance '{self.current_instance}'. Halting scan.")
            return

        rem = self.get_screen_quota()
        if rem is not None:
            logger.info(f"[{self.current_instance}] Auction House active. Live quota on screen: {rem}/500 remaining.")

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
                ok = self.run_query_collection(item, max_pages=pages, target_tab=target_tab)
                if not ok:
                    # Screen quota < 2
                    rotated = False
                    if self.allow_instance_rotation:
                        req = 2 if target_tab == "both" else 1
                        rotated = self.rotate_to_next_available(required=req)
                        if rotated:
                            self.run_query_collection(item, max_pages=pages, target_tab=target_tab)
                    if not rotated:
                        # All instances exhausted: safely leave auction and pause until 8:00 AM next day
                        self.leave_auction()
                        pause_until_next_8am(self.current_instance)
                        self.ensure_focus()
                        self.run_query_collection(item, max_pages=pages, target_tab=target_tab)
            except Exception as e:
                logger.error(f"Error processing item '{item}': {e}")
                failed_items.append(item)
            human_delay(1.5, 2.5)

        # Autonomous Retry Pass: Zero human intervention needed
        if failed_items and self.is_auction_open():
            logger.info(f"=== Autonomous Retry Pass: Re-attempting {len(failed_items)} failed items ===")
            for f_item in failed_items:
                try:
                    self.run_query_collection(f_item, max_pages=pages, target_tab=target_tab)
                except Exception as e:
                    logger.error(f"Retry failed for '{f_item}': {e}")
                human_delay(2.0, 3.0)

        logger.info("Catalog collection scan completed.")
        try:
            self.leave_auction()
        except Exception:
            pass

        # Autonomous Tier Evaluation Pass
        try:
            evaluator = TierEvaluator()
            evaluator.evaluate_and_update_watchlist()
        except Exception as e:
            logger.debug(f"Tier re-evaluation error: {e}")

    def shutdown(self):
        """
        Safely leaves Auction House and shuts down background OCR workers cleanly.
        """
        try:
            self.leave_auction()
        except Exception as e:
            logger.debug(f"Error leaving auction on shutdown: {e}")
        if hasattr(self, "ocr_worker"):
            self.ocr_worker.shutdown()


