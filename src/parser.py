import re
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from PIL import Image
from .models import ActiveListing, MatchedTrade, SearchQuota
from .ocr_engine import preprocess_for_ocr, ocr_image, extract_number, normalize_item_name

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
        Uses multi-box sampling and character normalization.
        """
        for box_coords in [
            (568, 88, 688, 124),  # Scaled on 1280x720: (710, 110, 860, 155)
            (576, 92, 688, 128),  # Scaled on 1280x720: (720, 115, 860, 160)
            (568, 88, 664, 128)
        ]:
            box = self._scale_box(*box_coords)
            crop = self.raw_image.crop(box)
            text = ocr_image(crop, lang="en-US")
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

        for y1, y2 in self.ROW_BOUNDS:
            # 1. Item Name
            name_box = self._scale_box(335, y1 + 4, 555, y2 - 4)
            name_crop = self.raw_image.crop(name_box).resize((450, 70), Image.Resampling.LANCZOS)
            raw_name = ocr_image(name_crop, lang="zh-Hant-TW")
            item_name = normalize_item_name(raw_name)

            if not item_name or len(item_name) < 2:
                continue

            # 2. Total Price
            tot_box = self._scale_box(550, y1, 675, y2)
            tot_crop = self.raw_image.crop(tot_box).resize((350, 100), Image.Resampling.LANCZOS)
            tot_text = ocr_image(tot_crop, lang="en-US")
            total_price = extract_number(tot_text)

            # 3. Unit Price
            unit_box = self._scale_box(675, y1, 790, y2)
            unit_crop = self.raw_image.crop(unit_box).resize((350, 100), Image.Resampling.LANCZOS)
            unit_text = ocr_image(unit_crop, lang="en-US")
            unit_price = extract_number(unit_text)

            # Fallbacks
            if unit_price is None and total_price is not None:
                unit_price = total_price
            elif total_price is None and unit_price is not None:
                total_price = unit_price

            if unit_price is None or unit_price <= 0:
                continue

            quantity = max(1, round(total_price / unit_price)) if total_price else 1

            # 4. Remaining Time & Seller ID
            meta_box = self._scale_box(795, y1, 925, y2)
            meta_crop = self.raw_image.crop(meta_box).resize((350, 100), Image.Resampling.LANCZOS)
            meta_text = ocr_image(meta_crop, lang="en-US")

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
        trades: List[MatchedTrade] = []

        for y1, y2 in self.ROW_BOUNDS:
            # 1. Item Name
            name_box = self._scale_box(335, y1 + 4, 555, y2 - 4)
            name_crop = self.raw_image.crop(name_box).resize((450, 70), Image.Resampling.LANCZOS)
            raw_name = ocr_image(name_crop, lang="zh-Hant-TW")
            item_name = normalize_item_name(raw_name)

            if not item_name or len(item_name) < 2:
                continue

            # 2. Total Price
            tot_box = self._scale_box(550, y1, 675, y2)
            tot_crop = self.raw_image.crop(tot_box).resize((350, 100), Image.Resampling.LANCZOS)
            tot_text = ocr_image(tot_crop, lang="en-US")
            total_price = extract_number(tot_text)

            # 3. Unit Price
            unit_box = self._scale_box(675, y1, 790, y2)
            unit_crop = self.raw_image.crop(unit_box).resize((350, 100), Image.Resampling.LANCZOS)
            unit_text = ocr_image(unit_crop, lang="en-US")
            unit_price = extract_number(unit_text)

            # Equipment or single sales show '-' for unit price
            if unit_price is None and total_price is not None:
                unit_price = total_price
            elif total_price is None and unit_price is not None:
                total_price = unit_price

            if unit_price is None or unit_price <= 0:
                continue

            # Quantity estimation with item-category sanity checks
            quantity = max(1, round(total_price / unit_price)) if (total_price and unit_price) else 1

            # Scrolls and equipment never sell in lots > 20. If quantity > 20, unit_price was misread by OCR.
            if any(k in item_name for k in ["卷軸", "頭盔", "臉部", "眼部", "墜飾", "耳環", "戒指"]):
                if quantity > 20:
                    unit_price = total_price
                    quantity = 1

            # 4. Matched Time & Trader
            meta_box = self._scale_box(795, y1, 925, y2)
            meta_crop = self.raw_image.crop(meta_box).resize((350, 100), Image.Resampling.LANCZOS)
            meta_text = ocr_image(meta_crop, lang="en-US")

            # Extract date time
            time_match = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", meta_text)
            if time_match:
                trade_time = time_match.group(1)
            else:
                short_time = re.search(r"(\d{2}:\d{2})", meta_text)
                trade_time = f"{datetime.now().strftime('%Y-%m-%d')} {short_time.group(1)}" if short_time else None

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
