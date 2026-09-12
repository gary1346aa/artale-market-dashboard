import re
from typing import List, Optional, Tuple
from PIL import Image
from .models import ActiveListing, MatchedTrade, SearchQuota
from .ocr_engine import preprocess_for_ocr, ocr_image, extract_number, normalize_item_name

class MarketParser:
    """
    Parser for Artale Market screenshots.
    Base reference resolution: 1024 x 576.
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

    def __init__(self, image: Image.Image):
        self.raw_image = image
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

    def parse_search_quota(self) -> Optional[SearchQuota]:
        """
        Extracts remaining search quota (e.g. '499/500').
        """
        box = self._scale_box(375, 10, 465, 32)
        crop = self.raw_image.crop(box)
        proc = preprocess_for_ocr(crop, scale=2.5, binarize=False)
        text = ocr_image(proc, lang="en-US")
        match = re.search(r"(\d+)\s*/\s*(\d+)", text)
        if match:
            return SearchQuota(
                current_used=int(match.group(1)),
                max_limit=int(match.group(2))
            )
        return None

    def parse_pagination(self) -> Optional[Tuple[int, int]]:
        """
        Extracts (current_page, total_pages) from the pagination control (e.g. '1 / 20').
        """
        box = self._scale_box(575, 95, 640, 130)
        crop = self.raw_image.crop(box)
        proc = preprocess_for_ocr(crop, scale=2.5, binarize=False)
        text = ocr_image(proc, lang="en-US")
        match = re.search(r"(\d+)\s*/\s*(\d+)", text)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return None

    def parse_active_listings(self) -> List[ActiveListing]:
        """
        Parses active sell listings from the '查詢' (Query / Listings) tab.
        """
        listings: List[ActiveListing] = []
        pagination = self.parse_pagination()
        curr_page = pagination[0] if pagination else 1

        for y1, y2 in self.ROW_BOUNDS:
            # 1. Item Name
            name_box = self._scale_box(335, y1 + 4, 555, y2 - 4)
            name_crop = self.raw_image.crop(name_box)
            proc_name = preprocess_for_ocr(name_crop, scale=2.5, binarize=False)
            raw_name = ocr_image(proc_name, lang="zh-Hant-TW")
            item_name = normalize_item_name(raw_name)

            if not item_name or len(item_name) < 2:
                continue

            # 2. Total Price (Cell bounds)
            tot_box = self._scale_box(550, y1, 675, y2)
            tot_crop = self.raw_image.crop(tot_box)
            proc_tot = preprocess_for_ocr(tot_crop, scale=2.5, binarize=False)
            tot_text = ocr_image(proc_tot, lang="en-US")
            total_price = extract_number(tot_text)

            # 3. Unit Price (Cell bounds)
            unit_box = self._scale_box(675, y1, 790, y2)
            unit_crop = self.raw_image.crop(unit_box)
            proc_unit = preprocess_for_ocr(unit_crop, scale=2.5, binarize=False)
            unit_text = ocr_image(proc_unit, lang="en-US")
            unit_price = extract_number(unit_text)

            # Fallbacks and sanity checks
            if unit_price is None and total_price is not None:
                unit_price = total_price
            elif total_price is None and unit_price is not None:
                total_price = unit_price

            if unit_price is None or unit_price <= 0:
                continue

            # Compute quantity from total / unit
            quantity = max(1, round(total_price / unit_price)) if total_price else 1

            # 4. Remaining Time & Seller ID
            meta_box = self._scale_box(805, y1, 915, y2)
            meta_crop = self.raw_image.crop(meta_box)
            proc_meta = preprocess_for_ocr(meta_crop, scale=2.0, binarize=False)
            meta_text = ocr_image(proc_meta, lang="en-US")

            lines = [l.strip() for l in meta_text.splitlines() if l.strip()]
            remaining_time = lines[0] if len(lines) > 0 else None
            seller_id = lines[1] if len(lines) > 1 else None

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
        # Calibrated once the layout of the 市價 tab is provided
        trades: List[MatchedTrade] = []
        return trades
