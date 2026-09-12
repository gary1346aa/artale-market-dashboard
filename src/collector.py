import logging
import time
import os
from typing import List, Optional
from .window_manager import WindowManager
from .parser import MarketParser
from .database import init_db, save_active_listings, save_matched_trades
from .actions import human_click, human_delay, clear_and_paste

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ArtaleCollector")

class MarketCollector:
    """
    Automates market scanning, tab navigation, OCR data collection, and DB persistence.
    Calibrated against Artale 1280x720 inner canvas (1024x576 reference coordinates).
    """
    # Exact calibrated reference coordinates (1024 x 576 base)
    POS_QUICK_SEARCH = (240, 30)      # Scaled to (300, 37) on 1280x720
    POS_QUERY_TAB = (195, 72)         # Scaled to (244, 90) on 1280x720
    POS_MARKET_TAB = (417, 72)        # Scaled to (522, 90) on 1280x720
    POS_SIDEBAR_SEARCH = (223, 261)   # Scaled to (279, 327) on 1280x720
    POS_START_SEARCH = (250, 442)     # Scaled to (312, 553) on 1280x720
    POS_NEXT_PAGE = (660, 112)
    POS_FIRST_PAGE = (518, 112)

    def __init__(self, window_mgr: Optional[WindowManager] = None):
        self.win_mgr = window_mgr or WindowManager()
        init_db()

    def ensure_focus(self) -> bool:
        if not self.win_mgr.find_window():
            logger.error("Could not find Artale / MapleStory Worlds game window. Please ensure the game is running.")
            return False
        self.win_mgr.bring_to_front()
        time.sleep(0.5)
        return True

    def click_ref(self, ref_x: int, ref_y: int):
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

    def execute_search(self, keyword: str) -> bool:
        """
        Inputs keyword into the quick search box and submits via Enter cleanly.
        """
        logger.info(f"Searching for item: '{keyword}'")
        search_pt = self.win_mgr.to_screen_coords(*self.POS_QUICK_SEARCH)
        if not search_pt:
            return False

        # Clear, paste Traditional Chinese without trailing character, and press Enter
        clear_and_paste(search_pt[0], search_pt[1], keyword)
        human_delay(1.5, 2.0)
        return True

    def scrape_current_page(self) -> dict:
        """
        Captures the screen, parses the current page, and saves records directly to DB.
        """
        frame = self.win_mgr.capture_frame()
        if not frame:
            logger.warning("Frame capture returned empty.")
            return {"tab": "unknown", "count": 0}

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
        else:
            save_active_listings(records)
            logger.info(f"[查詢] Captured {len(records)} active listings from page.")

        return {
            "tab": tab,
            "quota": res["quota"],
            "pagination": res["pagination"],
            "count": len(records)
        }

    def paginate_and_scrape(self, max_pages: int = 3):
        """
        Scrapes current tab across multiple pages up to max_pages.
        """
        for page_idx in range(1, max_pages + 1):
            info = self.scrape_current_page()
            pagination = info.get("pagination")

            if pagination:
                curr_p, total_p = pagination
                logger.info(f"Scraped page {curr_p} of {total_p}")
                if curr_p >= total_p or page_idx >= max_pages:
                    break
            elif page_idx >= max_pages:
                break

            # Click next page
            logger.info("Clicking next page button...")
            self.click_ref(*self.POS_NEXT_PAGE)
            human_delay(1.0, 1.5)

    def run_query_collection(self, keyword: str, max_pages: int = 2, check_both_tabs: bool = True):
        """
        Performs search for a keyword and collects both active listings and trade history.
        """
        if not self.ensure_focus():
            return

        # 1. Always switch to 查詢 tab first
        self.switch_to_tab("query")
        
        # 2. Perform search
        self.execute_search(keyword)

        # 3. Scrape Active Listings (查詢)
        self.paginate_and_scrape(max_pages=max_pages)

        # 4. Scrape Matched Trades (市價)
        if check_both_tabs:
            self.switch_to_tab("market")
            self.paginate_and_scrape(max_pages=max_pages)

    def run_catalog_scan(self, keywords: List[str], max_pages_per_query: int = 2):
        """
        Iterates over a list of items and captures market data.
        """
        logger.info(f"Starting catalog collection scan for {len(keywords)} items...")
        for idx, item in enumerate(keywords, 1):
            logger.info(f"--- Processing [{idx}/{len(keywords)}]: '{item}' ---")
            self.run_query_collection(item, max_pages=max_pages_per_query, check_both_tabs=True)
            human_delay(1.5, 2.5)

        logger.info("Catalog collection scan completed.")
