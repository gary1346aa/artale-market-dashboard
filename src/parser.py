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

        for y1, y2 in self.ROW_BOUNDS:
            # 1. Item Name - Column 1 (x: 350 to 560, avoids icon)
            name_box = self._scale_box(350, y1 + 4, 560, y2 - 4)
            name_crop = self.raw_image.crop(name_box).resize((450, 70), Image.Resampling.LANCZOS)
            raw_name = ocr_image(name_crop, lang="zh-Hant-TW")
            item_name = normalize_item_name(raw_name)

            if self.expected_item_name:
                if not item_name or len(item_name) < 2:
                    item_name = self.expected_item_name
                elif self.expected_item_name in item_name or item_name in self.expected_item_name:
                    item_name = self.expected_item_name
            elif not item_name or len(item_name) < 2:
                continue

            # 2. Total Price (Amount) - Column 2 (x: 570 to 685, shifted right)
            tot_box = self._scale_box(570, y1, 685, y2)
            tot_crop = self.raw_image.crop(tot_box).resize((350, 100), Image.Resampling.LANCZOS)
            tot_text = ocr_image(tot_crop, lang="en-US")
            total_price = extract_number(tot_text)
            if total_price is None:
                tot_text = ocr_image(tot_crop, lang="zh-Hant-TW")
                total_price = extract_number(tot_text)

            # 3. Unit Price - Column 3 (x: 690 to 800, shifted right)
            unit_box = self._scale_box(690, y1, 800, y2)
            unit_crop = self.raw_image.crop(unit_box).resize((350, 100), Image.Resampling.LANCZOS)
            unit_text = ocr_image(unit_crop, lang="en-US")
            unit_price = extract_number(unit_text)
            if unit_price is None:
                unit_text = ocr_image(unit_crop, lang="zh-Hant-TW")
                unit_price = extract_number(unit_text)

            # If both price columns are empty, the row is empty (end of results)
            if total_price is None and unit_price is None:
                continue

            # Equipment or single sales show '-' for unit price
            if unit_price is None and total_price is not None:
                unit_price = total_price
            elif total_price is None and unit_price is not None:
                total_price = unit_price

            # In Artale, minimum auction price is 500 mesos.
            # If unit_price < 500 (e.g. OCR read '-' as noise), fallback to total_price if valid
            if unit_price is not None and unit_price < 500:
                if total_price and total_price >= 500:
                    unit_price = total_price
                else:
                    continue

            if unit_price is None or unit_price < 500:
                continue

            # Total price and unit price are separate columns; quantity is strictly total_price / unit_price
            # In Artale, maximum stack/bundle quantity limit in auction house is 9,900
            quantity = max(1, min(9900, round(total_price / unit_price))) if (total_price and unit_price) else 1

            # Scrolls, equipment, and skill books category guard (single items)
            if any(k in item_name for k in ["卷軸", "頭盔", "臉部", "眼部", "墜飾", "耳環", "戒指", "技能書", "楓葉祝福", "挑釁"]):
                if quantity > 20:
                    unit_price = total_price
                    quantity = 1

            if unit_price < 500:
                continue

            # 4. Remaining Time (x: 818 to 925, y: y1+6 to y1+33, excludes user ID)
            meta_box = self._scale_box(818, y1 + 6, 925, y1 + 33)
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

        for y1, y2 in self.ROW_BOUNDS:
            # 1. Item Name - Column 1 (x: 350 to 560, avoids icon)
            name_box = self._scale_box(350, y1 + 4, 560, y2 - 4)
            name_crop = self.raw_image.crop(name_box).resize((450, 70), Image.Resampling.LANCZOS)
            raw_name = ocr_image(name_crop, lang="zh-Hant-TW")
            item_name = normalize_item_name(raw_name)

            if self.expected_item_name:
                if not item_name or len(item_name) < 2:
                    item_name = self.expected_item_name
                elif self.expected_item_name in item_name or item_name in self.expected_item_name:
                    item_name = self.expected_item_name
            elif not item_name or len(item_name) < 2:
                continue

            # 2. Total Price (Amount) - Column 2 (x: 570 to 685, shifted right)
            tot_box = self._scale_box(570, y1, 685, y2)
            tot_crop = self.raw_image.crop(tot_box).resize((350, 100), Image.Resampling.LANCZOS)
            tot_text = ocr_image(tot_crop, lang="en-US")
            total_price = extract_number(tot_text)
            if total_price is None:
                tot_text = ocr_image(tot_crop, lang="zh-Hant-TW")
                total_price = extract_number(tot_text)

            # 3. Unit Price - Column 3 (x: 690 to 800, shifted right)
            unit_box = self._scale_box(690, y1, 800, y2)
            unit_crop = self.raw_image.crop(unit_box).resize((350, 100), Image.Resampling.LANCZOS)
            unit_text = ocr_image(unit_crop, lang="en-US")
            unit_price = extract_number(unit_text)
            if unit_price is None:
                unit_text = ocr_image(unit_crop, lang="zh-Hant-TW")
                unit_price = extract_number(unit_text)

            # If both price columns are empty, the row is empty (end of results)
            if total_price is None and unit_price is None:
                continue

            # Equipment or single sales show '-' for unit price
            if unit_price is None and total_price is not None:
                unit_price = total_price
            elif total_price is None and unit_price is not None:
                total_price = unit_price

            # In Artale, minimum auction price is 500 mesos.
            # If unit_price < 500 (e.g. OCR read '-' as noise), fallback to total_price if valid
            if unit_price is not None and unit_price < 500:
                if total_price and total_price >= 500:
                    unit_price = total_price
                else:
                    continue

            if unit_price is None or unit_price < 500:
                continue

            # Total price and unit price are separate columns; quantity is strictly total_price / unit_price
            # In Artale, maximum stack/bundle quantity limit in auction house is 9,900
            quantity = max(1, min(9900, round(total_price / unit_price))) if (total_price and unit_price) else 1

            # Scrolls, equipment, and skill books category guard (single items)
            if any(k in item_name for k in ["卷軸", "頭盔", "臉部", "眼部", "墜飾", "耳環", "戒指", "技能書", "楓葉祝福", "挑釁"]):
                if quantity > 20:
                    unit_price = total_price
                    quantity = 1

            # 4. Matched Time (x: 818 to 925, y: y1+6 to y1+33, excludes user ID)
            meta_box = self._scale_box(818, y1 + 6, 925, y1 + 33)
            meta_crop = self.raw_image.crop(meta_box).resize((350, 75), Image.Resampling.LANCZOS)
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
