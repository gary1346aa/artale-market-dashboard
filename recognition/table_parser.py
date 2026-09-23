"""Auction House table parser and record assembler.

Extracts tabular listing rows and matched trade rows from screen frames,
dispatching numeric cells to the bitmask digit engine and text cells to OCR.
"""

from datetime import datetime, timedelta
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from config.coordinates import (
    PAGINATION_BOXES,
    ROW_BOUNDS_1280,
    Rect,
)
from config.settings import PROJECT_ROOT
from core.models import ActiveListing, MatchedTrade
from recognition.digit_engine import parse_price_cell, parse_timestamp_cell
from recognition.text_ocr import (
    extract_number,
    get_canonical_watchlist,
    normalize_item_name,
    ocr_image,
)

_logger = logging.getLogger(__name__)

FAILED_CROPS_DIR = PROJECT_ROOT / "data" / "unprocessed_crops"
CANONICAL_WIDTH = 1280
CANONICAL_HEIGHT = 720


class MarketParser:
    """Parses tabular data from Artale Market screenshots.

    Supports both '查詢' (Active Listings) and '市價' (Matched Trades) tabs.

    Attributes:
        raw_image: Input screenshot as a PIL Image.
        expected_item_name: Optional expected item name for validation.
        scale_x: Horizontal scale factor relative to 1280x720 canvas.
        scale_y: Vertical scale factor relative to 1280x720 canvas.
    """
    ROW_BOUNDS: List[Tuple[int, int]] = ROW_BOUNDS_1280


    def __init__(
        self, image: Image.Image, item_name: Optional[str] = None
    ) -> None:
        """Initializes MarketParser with an image and optional item name."""
        self.raw_image = image
        self.expected_item_name = item_name
        w, h = image.size
        self.scale_x = w / CANONICAL_WIDTH
        self.scale_y = h / CANONICAL_HEIGHT

    def _scale_box(
        self, x1: int, y1: int, x2: int, y2: int
    ) -> Tuple[int, int, int, int]:
        """Scales bounding box coordinates from canonical 1280x720 to actual image."""
        return (
            int(x1 * self.scale_x),
            int(y1 * self.scale_y),
            int(x2 * self.scale_x),
            int(y2 * self.scale_y),
        )

    def _save_failed_crop(
        self,
        crop_image: Image.Image,
        reason: str,
        row_idx: int,
        item_name: str = "",
    ) -> None:
        """Saves problematic row crop for inspection."""
        try:
            FAILED_CROPS_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            safe_name = (
                re.sub(r"[^\w\-_\.]", "_", item_name) if item_name else "unknown"
            )
            filename = f"failed_row_{ts}_{safe_name}_r{row_idx}_{reason}.png"
            crop_image.save(FAILED_CROPS_DIR / filename)
        except Exception as err:
            _logger.debug(f"Failed to save debug crop: {err}")

    def detect_active_tab(self) -> str:
        """Detects whether '查詢' (query) or '市價' (market) tab is active.

        Checks cyan color intensity on the tab header region.

        Returns:
            'market' for the 市價 tab, 'query' for the 查詢 tab.
        """
        # Canonical 1280x720 coordinates for market tab header
        crop_market = self.raw_image.crop(
            self._scale_box(387, 75, 625, 106)
        )
        cyan_count = 0
        for p in crop_market.getdata():
            r, g, b = p[0], p[1], p[2]
            if b > 100 and g > 100 and b > r + 30:
                cyan_count += 1

        return "market" if cyan_count > 50 else "query"

    def parse_pagination(self) -> Optional[Tuple[int, int]]:
        """Extracts current and total page numbers from the pagination control.

        Returns:
            Tuple of (current_page, total_pages) or None if not found.
        """
        # Pass 1: Raw 1x resolution across candidate boxes
        for box in PAGINATION_BOXES:
            scaled_coords = self._scale_box(box.x1, box.y1, box.x2, box.y2)
            crop = self.raw_image.crop(scaled_coords)
            for lang in ("en-US", "zh-Hant-TW"):
                text = ocr_image(crop, lang=lang)
                cleaned = (
                    text.replace("B", "8")
                    .replace("O", "0")
                    .replace("o", "0")
                    .replace("S", "5")
                    .replace("s", "5")
                )
                match = re.search(r"(\d+)\s*[/\|lI\\]\s*(\d+)", cleaned)
                if match:
                    curr, total = int(match.group(1)), int(match.group(2))
                    if 1 <= curr <= total:
                        return curr, total

        # Pass 2: 2x BICUBIC magnification fallback
        for box in PAGINATION_BOXES:
            scaled_coords = self._scale_box(box.x1, box.y1, box.x2, box.y2)
            crop = self.raw_image.crop(scaled_coords)
            w, h = crop.size
            resized = crop.resize((w * 2, h * 2), Image.Resampling.BICUBIC)
            for lang in ("zh-Hant-TW", "en-US"):
                text = ocr_image(resized, lang=lang)
                cleaned = (
                    text.replace("B", "8")
                    .replace("O", "0")
                    .replace("o", "0")
                    .replace("S", "5")
                    .replace("s", "5")
                )
                match = re.search(r"(\d+)\s*[/\|lI\\]\s*(\d+)", cleaned)
                if match:
                    curr, total = int(match.group(1)), int(match.group(2))
                    if 1 <= curr <= total:
                        return curr, total

        return None

    def parse_active_listings(self) -> List[ActiveListing]:
        """Parses active sell listings from the '查詢' (Query / Listings) tab.

        Returns:
            List of parsed ActiveListing models.
        """
        listings: List[ActiveListing] = []
        pagination = self.parse_pagination()
        curr_page = pagination[0] if pagination else 1

        for row_idx, (y1, y2) in enumerate(ROW_BOUNDS_1280):
            # 1. Item Name - Column 1 (x: 456 to 693, clean title without icon)
            name_box = self._scale_box(456, y1 + 5, 693, y2 - 5)
            name_crop = self.raw_image.crop(name_box).resize(
                (450, 70), Image.Resampling.LANCZOS
            )
            raw_name = ocr_image(name_crop, lang="zh-Hant-TW")
            item_name = normalize_item_name(raw_name)

            if self.expected_item_name:
                canonical = get_canonical_watchlist()
                if self.expected_item_name in canonical:
                    item_name = self.expected_item_name
                elif not item_name or len(item_name) < 2:
                    item_name = self.expected_item_name
                elif (
                    self.expected_item_name in item_name
                    or item_name in self.expected_item_name
                ):
                    item_name = self.expected_item_name
            elif not item_name or len(item_name) < 2:
                continue

            # 2. Total Price (Amount) - Column 2
            tot_crop = self.raw_image.crop(
                self._scale_box(687, y1, 844, y2)
            )
            total_price = parse_price_cell(tot_crop, tab="query")
            if total_price is None:
                tot_ocr_crop = self.raw_image.crop(
                    self._scale_box(725, y1, 860, y1 + 32)
                ).resize((350, 70), Image.Resampling.LANCZOS)
                tot_text = ocr_image(tot_ocr_crop, lang="en-US") or ocr_image(
                    tot_ocr_crop, lang="zh-Hant-TW"
                )
                total_price = extract_number(tot_text)

            # 3. Unit Price - Column 3
            unit_crop = self.raw_image.crop(
                self._scale_box(844, y1, 987, y2)
            )
            unit_price = parse_price_cell(unit_crop, tab="query")
            if unit_price is None:
                unit_ocr_crop = self.raw_image.crop(
                    self._scale_box(881, y1, 1006, y1 + 32)
                ).resize((350, 70), Image.Resampling.LANCZOS)
                unit_text = ocr_image(unit_ocr_crop, lang="en-US") or ocr_image(
                    unit_ocr_crop, lang="zh-Hant-TW"
                )
                unit_price = extract_number(unit_text)

            if total_price is None and unit_price is None:
                continue

            row_box = self._scale_box(456, y1, 1150, y2)
            row_crop = self.raw_image.crop(row_box)

            if unit_price is None and total_price is not None:
                if 500 <= total_price <= 30_000_000_000:
                    unit_price = total_price
                    quantity = 1
                else:
                    self._save_failed_crop(
                        row_crop, "price_out_of_bounds", row_idx, item_name
                    )
                    continue
            elif total_price is not None and unit_price is not None:
                if (
                    unit_price < 500
                    or unit_price > 30_000_000_000
                    or total_price < 500
                    or total_price > 30_000_000_000
                ):
                    self._save_failed_crop(
                        row_crop, "price_out_of_bounds", row_idx, item_name
                    )
                    continue
                if total_price < unit_price:
                    self._save_failed_crop(
                        row_crop, "total_less_than_unit", row_idx, item_name
                    )
                    continue
                if total_price % unit_price != 0:
                    self._save_failed_crop(
                        row_crop, "not_divisible", row_idx, item_name
                    )
                    continue
                quantity = total_price // unit_price
                if quantity < 1 or quantity > 9900:
                    self._save_failed_crop(
                        row_crop,
                        f"qty_out_of_bounds_{quantity}",
                        row_idx,
                        item_name,
                    )
                    continue
            else:
                self._save_failed_crop(
                    row_crop, "missing_total_price", row_idx, item_name
                )
                continue

            # 4. Remaining Time (Column 4)
            meta_box = self._scale_box(1027, y1 + 7, 1150, y1 + 41)
            meta_crop = self.raw_image.crop(meta_box).resize(
                (350, 75), Image.Resampling.LANCZOS
            )
            meta_text = ocr_image(meta_crop, lang="zh-Hant-TW")
            remaining_time = (
                meta_text.replace("\n", " ").strip() if meta_text else None
            )

            listings.append(
                ActiveListing(
                    item_name=item_name,
                    quantity=quantity,
                    total_price=total_price,
                    unit_price=unit_price,
                    remaining_time=remaining_time,
                    page_number=curr_page,
                )
            )

        return listings

    def parse_matched_trades(self) -> List[MatchedTrade]:
        """Parses completed historical transactions from the '市價' tab.

        Returns:
            List of parsed MatchedTrade models.
        """
        trades: List[MatchedTrade] = []

        for row_idx, (y1, y2) in enumerate(ROW_BOUNDS_1280):
            # 1. Item Name - Column 1
            name_box = self._scale_box(456, y1 + 5, 693, y2 - 5)
            name_crop = self.raw_image.crop(name_box).resize(
                (450, 70), Image.Resampling.LANCZOS
            )
            raw_name = ocr_image(name_crop, lang="zh-Hant-TW")
            item_name = normalize_item_name(raw_name)

            if self.expected_item_name:
                canonical = get_canonical_watchlist()
                if self.expected_item_name in canonical:
                    item_name = self.expected_item_name
                elif not item_name or len(item_name) < 2:
                    item_name = self.expected_item_name
                elif (
                    self.expected_item_name in item_name
                    or item_name in self.expected_item_name
                ):
                    item_name = self.expected_item_name
            elif not item_name or len(item_name) < 2:
                continue

            # 2. Total Price - Column 2
            tot_crop = self.raw_image.crop(
                self._scale_box(687, y1, 844, y2)
            )
            total_price = parse_price_cell(tot_crop, tab="market")
            if total_price is None:
                tot_ocr_crop = self.raw_image.crop(
                    self._scale_box(725, y1, 860, y1 + 32)
                ).resize((350, 70), Image.Resampling.LANCZOS)
                tot_text = ocr_image(tot_ocr_crop, lang="en-US") or ocr_image(
                    tot_ocr_crop, lang="zh-Hant-TW"
                )
                total_price = extract_number(tot_text)

            # 3. Unit Price - Column 3
            unit_crop = self.raw_image.crop(
                self._scale_box(844, y1, 987, y2)
            )
            unit_price = parse_price_cell(unit_crop, tab="market")
            if unit_price is None:
                unit_ocr_crop = self.raw_image.crop(
                    self._scale_box(881, y1, 1006, y1 + 32)
                ).resize((350, 70), Image.Resampling.LANCZOS)
                unit_text = ocr_image(unit_ocr_crop, lang="en-US") or ocr_image(
                    unit_ocr_crop, lang="zh-Hant-TW"
                )
                unit_price = extract_number(unit_text)

            if total_price is None and unit_price is None:
                continue

            row_box = self._scale_box(456, y1, 1150, y2)
            row_crop = self.raw_image.crop(row_box)

            if unit_price is None and total_price is not None:
                if 500 <= total_price <= 30_000_000_000:
                    unit_price = total_price
                    quantity = 1
                else:
                    self._save_failed_crop(
                        row_crop, "price_out_of_bounds", row_idx, item_name
                    )
                    continue
            elif total_price is not None and unit_price is not None:
                if (
                    unit_price < 500
                    or unit_price > 30_000_000_000
                    or total_price < 500
                    or total_price > 30_000_000_000
                ):
                    self._save_failed_crop(
                        row_crop, "price_out_of_bounds", row_idx, item_name
                    )
                    continue
                if total_price < unit_price:
                    self._save_failed_crop(
                        row_crop, "total_less_than_unit", row_idx, item_name
                    )
                    continue
                if total_price % unit_price != 0:
                    self._save_failed_crop(
                        row_crop, "not_divisible", row_idx, item_name
                    )
                    continue
                quantity = total_price // unit_price
                if quantity < 1 or quantity > 9900:
                    self._save_failed_crop(
                        row_crop,
                        f"qty_out_of_bounds_{quantity}",
                        row_idx,
                        item_name,
                    )
                    continue
            else:
                self._save_failed_crop(
                    row_crop, "missing_total_price", row_idx, item_name
                )
                continue

            # 4. Matched Time (Column 4)
            meta_box = self._scale_box(1027, y1 + 7, 1150, y1 + 41)
            meta_crop = self.raw_image.crop(meta_box)
            trade_time = parse_timestamp_cell(meta_crop)

            if not trade_time:
                meta_ocr_crop = meta_crop.resize(
                    (350, 75), Image.Resampling.LANCZOS
                )
                meta_text = ocr_image(meta_ocr_crop, lang="en-US")
                time_match = re.search(
                    r"(?P<year>202\d|2\d)\D+(?P<month>0?[1-9]|1[0-2])\D+"
                    r"(?P<day>0?[1-9]|[12]\d|3[01])\D+(?P<hour>[01]?\d|2[0-3])"
                    r"\D+(?P<minute>[0-5]\d)",
                    meta_text,
                )
                if time_match:
                    d = time_match.groupdict()
                    y = "20" + d["year"] if len(d["year"]) == 2 else d["year"]
                    trade_time = (
                        f"{y}-{int(d['month']):02d}-{int(d['day']):02d} "
                        f"{int(d['hour']):02d}:{int(d['minute']):02d}"
                    )
                else:
                    short_match = re.search(
                        r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)",
                        meta_text,
                    )
                    if short_match:
                        h = int(short_match.group("hour"))
                        mi = int(short_match.group("minute"))
                        now = datetime.now()
                        if (h, mi) > (now.hour, now.minute):
                            trade_date = (now - timedelta(days=1)).strftime(
                                "%Y-%m-%d"
                            )
                        else:
                            trade_date = now.strftime("%Y-%m-%d")
                        trade_time = f"{trade_date} {h:02d}:{mi:02d}"
                    else:
                        trade_time = None

            if not trade_time:
                self._save_failed_crop(
                    row_crop, "unparseable_trade_time", row_idx, item_name
                )
                continue

            trades.append(
                MatchedTrade(
                    item_name=item_name,
                    quantity=quantity,
                    matched_unit_price=unit_price,
                    total_matched_price=total_price,
                    trade_time=trade_time,
                )
            )

        return trades

    def parse(self) -> Dict[str, Any]:
        """Auto-detects active tab and extracts listings or matched trades.

        Returns:
            Dict containing 'tab', 'pagination', and 'records'.
        """
        tab = self.detect_active_tab()
        pagination = self.parse_pagination()

        if tab == "market":
            records = self.parse_matched_trades()
        else:
            records = self.parse_active_listings()

        return {
            "tab": tab,
            "pagination": pagination,
            "records": records,
        }
