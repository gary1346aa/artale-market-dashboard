"""Deterministic bitmask digit and timestamp recognition engine.

Implements O(1) bitmask hash lookups and 2D shift-invariant
minimum Hamming distance fallbacks calibrated against in-game fonts.
"""

from typing import List, Optional, Tuple

from PIL import Image

from config.coordinates import REGION_QUOTA_DIGITS
from recognition.glyph_table import ALL_PROTOTYPES, EXACT_GLYPHS


def match_glyph(crop: Image.Image) -> str:
    """Matches a 10px high binary glyph to its digit representation.

    Uses an instantaneous O(1) exact bitmask hash lookup followed by a
    bitwise shift-invariant minimum Hamming distance fallback across
    shifts (dx in {-1, 0, 1}, dy in {-1, 0, 1}).

    Args:
        crop: PIL Image in mode '1' (binary) or grayscale, exactly 10px high.

    Returns:
        Recognized single digit character string ('0'-'9').
    """
    gw, _ = crop.size
    if gw <= 2:
        return "1"

    # Extract 10-row bitmask tuple
    b = tuple(
        sum(crop.getpixel((x, y)) << x for x in range(gw)) for y in range(10)
    )

    # 1. Exact O(1) hash lookup
    if (b, gw) in EXACT_GLYPHS:
        return EXACT_GLYPHS[(b, gw)]

    # 2. Bitwise 2D Shift-Invariant Hamming fallback
    best_d = "0"
    min_dist = 999
    for d, tb, tw in ALL_PROTOTYPES:
        if abs(tw - gw) > 2:
            continue
        for dy in (-1, 0, 1):
            if dy == 1:
                shifted_b = (0,) + b[:9]
            elif dy == -1:
                shifted_b = b[1:] + (0,)
            else:
                shifted_b = b

            for dx in (-1, 0, 1):
                if dx > 0:
                    dist = sum(
                        (r1 ^ (r2 << dx)).bit_count()
                        for r1, r2 in zip(shifted_b, tb)
                    )
                elif dx < 0:
                    dist = sum(
                        (r1 ^ (r2 >> (-dx))).bit_count()
                        for r1, r2 in zip(shifted_b, tb)
                    )
                else:
                    dist = sum(
                        (r1 ^ r2).bit_count() for r1, r2 in zip(shifted_b, tb)
                    )

                if dist < min_dist:
                    min_dist = dist
                    best_d = d
                    if min_dist == 0:
                        return best_d

    return best_d


def parse_price_cell(
    cell_crop: Optional[Image.Image], tab: str = "market"
) -> Optional[int]:
    """Deterministically parses numeric prices from an Auction House cell crop.

    Supports both 'market' tab (gold text) and 'query' tab (white text).
    Ignores commas and currency symbols automatically.

    Args:
        cell_crop: Cropped image of the price column cell.
        tab: 'market' for completed trades, 'query' for active sell listings.

    Returns:
        Integer price in mesos, or None if the cell is empty or invalid.
    """
    if cell_crop is None:
        return None

    w, h = cell_crop.size
    # Calibrated for canonical 1280x720 canvas (row crop height >= 50px)
    if h < 50 or w < 140:
        return None

    thresh = 110 if tab == "market" else 135
    gray = cell_crop.convert("L")

    # Dynamic vertical baseline detection (skips left border x < 15)
    row_sums = [
        sum(1 for x in range(15, w) if gray.getpixel((x, y)) > thresh)
        for y in range(h)
    ]
    cands = [y for y in range(14, min(32, h)) if row_sums[y] >= 5]
    if not cands:
        return None
    top_y = min(cands)
    if top_y + 10 > h:
        return None

    strip = gray.crop((0, top_y, w, top_y + 10)).point(
        lambda p: 1 if p > thresh else 0
    )

    # Clean out comma artifacts (blank upper rows 0..5, active lower rows 6..9)
    clean_strip = strip.copy()
    for x in range(w):
        upper_sum = sum(strip.getpixel((x, y)) for y in range(6))
        lower_sum = sum(strip.getpixel((x, y)) for y in range(6, 10))
        if upper_sum == 0 and lower_sum > 0:
            for y in range(6, 10):
                clean_strip.putpixel((x, y), 0)

    # Segment columns into spans
    col_sums = [
        sum(clean_strip.getpixel((x, y)) for y in range(10)) for x in range(w)
    ]
    spans: List[Tuple[int, int]] = []
    in_glyph = False
    start = 0
    for x in range(w):
        if col_sums[x] > 0 and not in_glyph:
            in_glyph = True
            start = x
        elif col_sums[x] == 0 and in_glyph:
            in_glyph = False
            spans.append((start, x))
    if in_glyph:
        spans.append((start, w))

    # Filter out coin icon / left-hand noise (x < 45)
    digit_spans = [sp for sp in spans if sp[0] >= 45]
    if not digit_spans:
        return None

    # Check if single item placeholder '-'
    if len(digit_spans) == 1 and (digit_spans[0][1] - digit_spans[0][0]) <= 5:
        return None

    digits: List[str] = []
    for s, e in digit_spans:
        gw = e - s
        if gw <= 8:
            digits.append(match_glyph(clean_strip.crop((s, 0, e, 10))))
        elif 12 <= gw <= 16:
            # 2 touching digits (e.g. 44, 00)
            digits.append(match_glyph(clean_strip.crop((s, 0, s + 7, 10))))
            digits.append(match_glyph(clean_strip.crop((e - 7, 0, e, 10))))
        elif 18 <= gw <= 24:
            # 3 touching digits
            mid = (s + e) // 2
            digits.append(match_glyph(clean_strip.crop((s, 0, s + 7, 10))))
            digits.append(
                match_glyph(clean_strip.crop((mid - 3, 0, mid + 4, 10)))
            )
            digits.append(match_glyph(clean_strip.crop((e - 7, 0, e, 10))))
        else:
            digits.append(match_glyph(clean_strip.crop((s, 0, e, 10))))

    val_str = "".join(digits)
    return int(val_str) if val_str.isdigit() else None


def parse_timestamp_cell(cell_crop: Optional[Image.Image]) -> Optional[str]:
    """Deterministically parses completed trade timestamps ('YYYY-MM-DD HH:MM').

    Args:
        cell_crop: Cropped image of the trade time cell.

    Returns:
        Formatted timestamp string 'YYYY-MM-DD HH:MM', or None if invalid.
    """
    if cell_crop is None:
        return None

    w, h = cell_crop.size
    if w < 110 or h < 30:
        return None

    thresh = 110
    gray = cell_crop.convert("L")

    # Dynamic vertical baseline detection
    row_sums = [
        sum(1 for x in range(w) if gray.getpixel((x, y)) > thresh)
        for y in range(h)
    ]
    cands = [y for y in range(12, min(28, h)) if row_sums[y] >= 5]
    if not cands:
        return None
    top_y = min(cands)
    if top_y + 10 > h:
        return None

    strip = gray.crop((0, top_y, w, top_y + 10)).point(
        lambda p: 1 if p > thresh else 0
    )

    col_sums = [sum(strip.getpixel((x, y)) for y in range(10)) for x in range(w)]
    spans: List[Tuple[int, int]] = []
    in_glyph = False
    start = 0
    for x in range(w):
        if col_sums[x] > 0 and not in_glyph:
            in_glyph = True
            start = x
        elif col_sums[x] == 0 and in_glyph:
            in_glyph = False
            spans.append((start, x))
    if in_glyph:
        spans.append((start, w))

    # Clean borders (x < 5 and x > 118)
    clean_spans = [sp for sp in spans if sp[0] >= 5 and sp[1] <= 118]

    # Expand any composite spans
    expanded_spans: List[Tuple[int, int]] = []
    for s, e in clean_spans:
        gw = e - s
        if gw <= 8:
            expanded_spans.append((s, e))
        elif 12 <= gw <= 16:
            expanded_spans.append((s, s + 7))
            expanded_spans.append((e - 7, e))
        elif 18 <= gw <= 24:
            mid = (s + e) // 2
            expanded_spans.append((s, s + 7))
            expanded_spans.append((mid - 3, mid + 4))
            expanded_spans.append((e - 7, e))
        else:
            expanded_spans.append((s, e))

    if len(expanded_spans) != 15:
        return None

    chars: List[str] = []
    for idx, (s, e) in enumerate(expanded_spans):
        if idx in (4, 7):
            chars.append("-")
        elif idx == 12:
            chars.append(":")
        else:
            chars.append(match_glyph(strip.crop((s, 0, e, 10))))

    ts_str = "".join(chars[:10]) + " " + "".join(chars[10:])

    # Quick validation of format: 202x-MM-DD HH:MM
    try:
        parts = ts_str.split(" ")
        date_parts = [int(p) for p in parts[0].split("-")]
        time_parts = [int(p) for p in parts[1].split(":")]
        if not (2020 <= date_parts[0] <= 2030):
            return None
        if not (1 <= date_parts[1] <= 12 and 1 <= date_parts[2] <= 31):
            return None
        if not (0 <= time_parts[0] <= 23 and 0 <= time_parts[1] <= 59):
            return None
        return ts_str
    except Exception:
        return None


def parse_quota_header(
    frame: Optional[Image.Image],
) -> Optional[Tuple[int, int]]:
    """Deterministically parses remaining Auction House search quota.

    Focuses strictly on the remaining quota digits ('XXX') located immediately
    before the slash on the header bar (canonical x=543..574, y=10..28).

    Args:
        frame: PIL Image of the game screen.

    Returns:
        Tuple of (remaining_searches, 500) if detected, or None if the screen
        is not in the Auction House or the header is obscured.
    """
    if frame is None:
        return None
    w, h = frame.size
    if w < 1000 or h < 600:
        return None

    # Scale coordinates if running on different resolution than canonical 1280x720
    sx, sy = w / 1280.0, h / 720.0
    crop_x1 = int(REGION_QUOTA_DIGITS.x1 * sx)
    crop_y1 = int(REGION_QUOTA_DIGITS.y1 * sy)
    crop_x2 = int(REGION_QUOTA_DIGITS.x2 * sx)
    crop_y2 = int(REGION_QUOTA_DIGITS.y2 * sy)

    cell = frame.crop((crop_x1, crop_y1, crop_x2, crop_y2))
    cw, ch = cell.size

    # Fast direct pixel lookup for bright yellow/gold text (R > 140, G > 120, B < 90)
    px = cell.load()
    mask = [
        [
            1
            if (px[x, y][0] > 140 and px[x, y][1] > 120 and px[x, y][2] < 90)
            else 0
            for x in range(cw)
        ]
        for y in range(ch)
    ]

    row_sums = [sum(row) for row in mask]
    cands = [y for y, s in enumerate(row_sums) if s >= 3]
    if not cands:
        return None

    top_y = min(cands)
    if top_y + 10 > ch:
        top_y = max(0, ch - 10)

    strip = Image.new("1", (cw, 10))
    for cy in range(10):
        y_src = top_y + cy
        if y_src < ch:
            for cx in range(cw):
                strip.putpixel((cx, cy), mask[y_src][cx])

    col_sums = [sum(strip.getpixel((x, y)) for y in range(10)) for x in range(cw)]
    spans: List[Tuple[int, int]] = []
    in_glyph = False
    start = 0
    for x in range(cw):
        if col_sums[x] > 0 and not in_glyph:
            in_glyph = True
            start = x
        elif col_sums[x] == 0 and in_glyph:
            in_glyph = False
            spans.append((start, x))
    if in_glyph:
        spans.append((start, cw))

    digits: List[str] = []
    for s, e in spans:
        gw = e - s
        glyph_crop = strip.crop((s, 0, e, 10))

        # If slash is reached, stop reading digits immediately
        if gw <= 4:
            c_sums = [
                sum(glyph_crop.getpixel((x, y)) for y in range(10))
                for x in range(gw)
            ]
            if max(c_sums) <= 4:
                break

        if gw <= 8:
            digits.append(match_glyph(glyph_crop))
        elif 12 <= gw <= 16:
            digits.append(match_glyph(glyph_crop.crop((0, 0, 7, 10))))
            digits.append(match_glyph(glyph_crop.crop((gw - 7, 0, gw, 10))))

    val_str = "".join(digits)
    if not val_str.isdigit():
        return None

    return int(val_str), 500
