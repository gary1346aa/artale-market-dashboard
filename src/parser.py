import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any
from PIL import Image
from .models import ActiveListing, MatchedTrade, SearchQuota
from .ocr_engine import preprocess_for_ocr, ocr_image, extract_number, normalize_item_name, get_canonical_watchlist
from .digit_engine import parse_price_cell, parse_timestamp_cell

UNPROCESSED_CROPS_DIR = Path(__file__).resolve().parent.parent / "data" / "unprocessed_crops"

class MarketParser:
    """
    Parser for Artale Market screenshots.
    Base reference resolution: 1024 x 576.
    Supports both '查詢' (Active Listings) and '市價' (Matched Trades) tabs.
    """
    REF_WIDTH = 1024
    REF_HEIGHT = 576

    # Fixed row bounds for 1024 x 576
    ROW_BOUNDS = [
        (155, 201),
        (202, 248),
        (249, 295),
        (296, 342),
        (343, 389),
        (390, 436),
        (437, 483)
    ]

    def __init__(self, image: Image.Image, item_name: Optional[str] = None):
        self.raw_image = image
        self.expected_item_name = item_name
        w, h = image.size
        self.scale_x = w / self.REF_WIDTH
        self.scale_y = h / self.REF_HEIGHT

    def _scale_box(self, x1: int, y1: int, x2: int, y2: int) -> Tuple[int, int, int, int]:
        return (
            int(x1 * self.scale_x),
            int(y1 * self.scale_y),
            int(x2 * self.scale_x),
            int(y2 * self.scale_y)
        )

    def _save_failed_crop(self, crop_image: Image.Image, reason: str, row_idx: int, item_name: str = ""):
        try:
            UNPROCESSED_CROPS_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            safe_name = re.sub(r'[^\w\-_\.]', '_', item_name) if item_name else "unknown"
            filename = f"failed_row_{ts}_{safe_name}_r{row_idx}_{reason}.png"
            crop_image.save(UNPROCESSED_CROPS_DIR / filename)
        except Exception:
            pass

    def detect_active_tab(self) -> str:
        """
        Detects whether '查詢' (query/sell price) or '市價' (market/match price) is active.
        Uses cyan color detection on the tab headers.
        """
        crop_market = self.raw_image.crop(self._scale_box(310, 60, 500, 85))
        cyan_count = 0
        for p in crop_market.getdata():
            r, g, b = p[0], p[1], p[2]
            if b > 100 and g > 100 and b > r + 30:
                cyan_count += 1
                
        if cyan_count > 50:
            return "market"
        return "query"

    def parse_search_quota(self) -> Optional[SearchQuota]:
        """
        Extracts remaining search quota (e.g. '498/500').
        """
        box = self._scale_box(375, 10, 465, 32)
        crop = self.raw_image.crop(box).resize((250, 60), Image.Resampling.LANCZOS)
        text = ocr_image(crop, lang="en-US")
        match = re.search(r"(\d+)\s*/\s*(\d+)", text)
        if match:
            return SearchQuota(
                current_used=int(match.group(1)),
                max_limit=int(match.group(2))
            )
        return None

    def parse_pagination(self) -> Optional[Tuple[int, int]]:
        """
        Extracts (current_page, total_pages) from the pagination control (e.g. '1 / 20' or '8 / 8').
        Uses multi-box sampling, raw 1x followed by 2x Bicubic fallback, and dual-language normalization.
        """
        boxes = [
            (568, 88, 688, 124),  # Scaled on 1280x720: (710, 110, 860, 155)
            (576, 92, 688, 128),  # Scaled on 1280x720: (720, 115, 860, 160)
            (568, 88, 664, 128)
        ]
        # Pass 1: raw 1x resolution (preserves crisp pixel art typography)
        for box_coords in boxes:
            box = self._scale_box(*box_coords)
            crop = self.raw_image.crop(box)
            for lang in ["en-US", "zh-Hant-TW"]:
                text = ocr_image(crop, lang=lang)
                cleaned = text.replace("B", "8").replace("O", "0").replace("o", "0").replace("S", "5").replace("s", "5")
                match = re.search(r"(\d+)\s*[/\|lI\\]\s*(\d+)", cleaned)
                if match:
                    curr, total = int(match.group(1)), int(match.group(2))
                    if 1 <= curr <= total:
                        return (curr, total)

        # Pass 2: 2x BICUBIC magnification fallback
        for box_coords in boxes:
            box = self._scale_box(*box_coords)
            crop = self.raw_image.crop(box)
            w, h = crop.size
            resized = crop.resize((w * 2, h * 2), Image.Resampling.BICUBIC)
            for lang in ["zh-Hant-TW", "en-US"]:
                text = ocr_image(resized, lang=lang)
                cleaned = text.replace("B", "8").replace("O", "0").replace("o", "0").replace("S", "5").replace("s", "5")
                match = re.search(r"(\d+)\s*[/\|lI\\]\s*(\d+)", cleaned)
                if match:
                    curr, total = int(match.group(1)), int(match.group(2))
                    if 1 <= curr <= total:
                        return (curr, total)

        return None

    def parse_active_listings(self) -> List[ActiveListing]:
        """
        Parses active sell listings from the '查詢' (Query / Listings) tab.
        """
        listings: List[ActiveListing] = []
        pagination = self.parse_pagination()
        curr_page = pagination[0] if pagination else 1

        for row_idx, (y1, y2) in enumerate(self.ROW_BOUNDS):
            # 1. Item Name - Column 1 (x: 365 to 555, clean title without icon border)
            name_box = self._scale_box(365, y1 + 4, 555, y2 - 4)
            name_crop = self.raw_image.crop(name_box).resize((450, 70), Image.Resampling.LANCZOS)
            raw_name = ocr_image(name_crop, lang="zh-Hant-TW")
            item_name = normalize_item_name(raw_name)

            if self.expected_item_name:
                if self.expected_item_name in get_canonical_watchlist():
                    item_name = self.expected_item_name
                elif not item_name or len(item_name) < 2:
                    item_name = self.expected_item_name
                elif self.expected_item_name in item_name or item_name in self.expected_item_name:
                    item_name = self.expected_item_name
            elif not item_name or len(item_name) < 2:
                continue

            # 2. Total Price (Amount) - Column 2
            tot_crop = self.raw_image.crop(self._scale_box(550, y1, 675, y2))
            total_price = parse_price_cell(tot_crop, tab="query")
            if total_price is None:
                # Safety fallback to OCR using tight single-line crop
                tot_ocr_crop = self.raw_image.crop(self._scale_box(580, y1, 688, y1 + 26)).resize((350, 70), Image.Resampling.LANCZOS)
                tot_text = ocr_image(tot_ocr_crop, lang="en-US") or ocr_image(tot_ocr_crop, lang="zh-Hant-TW")
                total_price = extract_number(tot_text)

            # 3. Unit Price - Column 3
            unit_crop = self.raw_image.crop(self._scale_box(675, y1, 790, y2))
            unit_price = parse_price_cell(unit_crop, tab="query")
            if unit_price is None:
                # Check if OCR can read a unit price (e.g. for legacy 1024x576 or bundle items)
                unit_ocr_crop = self.raw_image.crop(self._scale_box(705, y1, 805, y1 + 26)).resize((350, 70), Image.Resampling.LANCZOS)
                unit_text = ocr_image(unit_ocr_crop, lang="en-US") or ocr_image(unit_ocr_crop, lang="zh-Hant-TW")
                unit_price = extract_number(unit_text)

            # If both price columns are empty, the row is empty (end of results)
            if total_price is None and unit_price is None:
                continue

            row_box = self._scale_box(365, y1, 920, y2)
            row_crop = self.raw_image.crop(row_box)

            # Equipment or single sales show '-' for unit price
            if unit_price is None and total_price is not None:
                if 500 <= total_price <= 30_000_000_000:
                    unit_price = total_price
                    quantity = 1
                else:
                    self._save_failed_crop(row_crop, "price_out_of_bounds", row_idx, item_name)
                    continue
            elif total_price is not None and unit_price is not None:
                if unit_price < 500 or unit_price > 30_000_000_000 or total_price < 500 or total_price > 30_000_000_000:
                    self._save_failed_crop(row_crop, "price_out_of_bounds", row_idx, item_name)
                    continue
                if total_price < unit_price:
                    self._save_failed_crop(row_crop, "total_less_than_unit", row_idx, item_name)
                    continue
                # Mathematical exact integer division (zero error)
                if total_price % unit_price != 0:
                    self._save_failed_crop(row_crop, "not_divisible", row_idx, item_name)
                    continue
                quantity = total_price // unit_price
                if quantity < 1 or quantity > 9900:
                    self._save_failed_crop(row_crop, f"qty_out_of_bounds_{quantity}", row_idx, item_name)
                    continue
            else:
                self._save_failed_crop(row_crop, "missing_total_price", row_idx, item_name)
                continue

            # 4. Remaining Time (x: 822 to 920, y: y1+6 to y1+33, excludes user ID)
            meta_box = self._scale_box(822, y1 + 6, 920, y1 + 33)
            meta_crop = self.raw_image.crop(meta_box).resize((350, 75), Image.Resampling.LANCZOS)
            meta_text = ocr_image(meta_crop, lang="zh-Hant-TW")
            remaining_time = meta_text.replace("\n", " ").strip() if meta_text else None
            seller_id = None

            listings.append(ActiveListing(
                item_name=item_name,
                quantity=quantity,
                total_price=total_price,
                unit_price=unit_price,
                remaining_time=remaining_time,
                seller_id=seller_id,
                page_number=curr_page
            ))

        return listings

    def parse_matched_trades(self) -> List[MatchedTrade]:
        """
        Parses historical matched transaction prices from the '市價' (Market / Match Price) tab.
        """
        trades: List[MatchedTrade] = []

        for row_idx, (y1, y2) in enumerate(self.ROW_BOUNDS):
            # 1. Item Name - Column 1 (x: 365 to 555, clean title without icon border)
            name_box = self._scale_box(365, y1 + 4, 555, y2 - 4)
            name_crop = self.raw_image.crop(name_box).resize((450, 70), Image.Resampling.LANCZOS)
            raw_name = ocr_image(name_crop, lang="zh-Hant-TW")
            item_name = normalize_item_name(raw_name)

            if self.expected_item_name:
                if self.expected_item_name in get_canonical_watchlist():
                    item_name = self.expected_item_name
                elif not item_name or len(item_name) < 2:
                    item_name = self.expected_item_name
                elif self.expected_item_name in item_name or item_name in self.expected_item_name:
                    item_name = self.expected_item_name
            elif not item_name or len(item_name) < 2:
                continue

            # 2. Total Price (Amount) - Column 2
            tot_crop = self.raw_image.crop(self._scale_box(550, y1, 675, y2))
            total_price = parse_price_cell(tot_crop, tab="market")
            if total_price is None:
                # Safety fallback to OCR using tight single-line crop
                tot_ocr_crop = self.raw_image.crop(self._scale_box(580, y1, 688, y1 + 26)).resize((350, 70), Image.Resampling.LANCZOS)
                tot_text = ocr_image(tot_ocr_crop, lang="en-US") or ocr_image(tot_ocr_crop, lang="zh-Hant-TW")
                total_price = extract_number(tot_text)

            # 3. Unit Price - Column 3
            unit_crop = self.raw_image.crop(self._scale_box(675, y1, 790, y2))
            unit_price = parse_price_cell(unit_crop, tab="market")
            if unit_price is None:
                # Check if OCR can read a unit price (e.g. for legacy 1024x576 or bundle items)
                unit_ocr_crop = self.raw_image.crop(self._scale_box(705, y1, 805, y1 + 26)).resize((350, 70), Image.Resampling.LANCZOS)
                unit_text = ocr_image(unit_ocr_crop, lang="en-US") or ocr_image(unit_ocr_crop, lang="zh-Hant-TW")
                unit_price = extract_number(unit_text)

            # If both price columns are empty, the row is empty (end of results)
            if total_price is None and unit_price is None:
                continue

            row_box = self._scale_box(365, y1, 920, y2)
            row_crop = self.raw_image.crop(row_box)

            # Equipment or single sales show '-' for unit price
            if unit_price is None and total_price is not None:
                if 500 <= total_price <= 30_000_000_000:
                    unit_price = total_price
                    quantity = 1
                else:
                    self._save_failed_crop(row_crop, "price_out_of_bounds", row_idx, item_name)
                    continue
            elif total_price is not None and unit_price is not None:
                if unit_price < 500 or unit_price > 30_000_000_000 or total_price < 500 or total_price > 30_000_000_000:
                    self._save_failed_crop(row_crop, "price_out_of_bounds", row_idx, item_name)
                    continue
                if total_price < unit_price:
                    self._save_failed_crop(row_crop, "total_less_than_unit", row_idx, item_name)
                    continue
                # Mathematical exact integer division (zero error)
                if total_price % unit_price != 0:
                    self._save_failed_crop(row_crop, "not_divisible", row_idx, item_name)
                    continue
                quantity = total_price // unit_price
                if quantity < 1 or quantity > 9900:
                    self._save_failed_crop(row_crop, f"qty_out_of_bounds_{quantity}", row_idx, item_name)
                    continue
            else:
                self._save_failed_crop(row_crop, "missing_total_price", row_idx, item_name)
                continue

            # 4. Matched Time (x: 822 to 920, y: y1+6 to y1+33, excludes user ID)
            meta_box = self._scale_box(822, y1 + 6, 920, y1 + 33)
            meta_crop = self.raw_image.crop(meta_box)
            trade_time = parse_timestamp_cell(meta_crop)

            if not trade_time:
                # Safety fallback to regex OCR
                meta_ocr_crop = meta_crop.resize((350, 75), Image.Resampling.LANCZOS)
                meta_text = ocr_image(meta_ocr_crop, lang="en-US")
                time_match = re.search(
                    r"(?P<year>202\d|2\d)\D+(?P<month>0?[1-9]|1[0-2])\D+(?P<day>0?[1-9]|[12]\d|3[01])\D+(?P<hour>[01]?\d|2[0-3])\D+(?P<minute>[0-5]\d)",
                    meta_text
                )
                if time_match:
                    d = time_match.groupdict()
                    y = '20' + d['year'] if len(d['year']) == 2 else d['year']
                    trade_time = f"{y}-{int(d['month']):02d}-{int(d['day']):02d} {int(d['hour']):02d}:{int(d['minute']):02d}"
                else:
                    short_match = re.search(r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)", meta_text)
                    if short_match:
                        h = int(short_match.group("hour"))
                        mi = int(short_match.group("minute"))
                        now = datetime.now()
                        if (h, mi) > (now.hour, now.minute):
                            trade_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                        else:
                            trade_date = now.strftime("%Y-%m-%d")
                        trade_time = f"{trade_date} {h:02d}:{mi:02d}"
                    else:
                        trade_time = None

            trades.append(MatchedTrade(
                item_name=item_name,
                quantity=quantity,
                matched_unit_price=unit_price,
                total_matched_price=total_price,
                trade_time=trade_time
            ))

        return trades

    def parse(self) -> Dict[str, Any]:
        """
        Auto-detects active tab and extracts listings or matched trades accordingly.
        """
        tab = self.detect_active_tab()
        quota = self.parse_search_quota()
        pagination = self.parse_pagination()

        if tab == "market":
            data = self.parse_matched_trades()
        else:
            data = self.parse_active_listings()

        return {
            "tab": tab,
            "quota": quota,
            "pagination": pagination,
            "records": data
        }
