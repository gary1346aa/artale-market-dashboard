"""Recognition package for Artale Market Tracker.

Provides bitmask digit engines, glyph tables, text OCR wrappers,
and table parsers for Auction House screen captures.
"""

from recognition.digit_engine import (
    match_glyph,
    parse_price_cell,
    parse_quota_header,
    parse_timestamp_cell,
)
from recognition.glyph_table import ALL_PROTOTYPES, EXACT_GLYPHS
from recognition.table_parser import MarketParser
from recognition.text_ocr import (
    extract_number,
    get_canonical_watchlist,
    normalize_item_name,
    ocr_image,
    preprocess_for_ocr,
)

__all__ = [
    "match_glyph",
    "parse_price_cell",
    "parse_quota_header",
    "parse_timestamp_cell",
    "ALL_PROTOTYPES",
    "EXACT_GLYPHS",
    "MarketParser",
    "extract_number",
    "get_canonical_watchlist",
    "normalize_item_name",
    "ocr_image",
    "preprocess_for_ocr",
]
