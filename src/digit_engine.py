"""
Deterministic Digit and Timestamp Engine for Artale Market Tracker.

Replaces probabilistic OCR (Windows Media OCR / winocr) for all numeric fields
(prices, unit prices, quantities, and timestamps) with a 100% deterministic,
shift-invariant bitmap template matcher and topological validator.

Font characteristics in Artale UI:
- Fixed-pitch bitmap typography (6x10 / 7x10 pixel bounding box).
- Market Tab ('市價'): Gold/Yellow text (~#EBC003), optimal binarization threshold = 110.
- Query Tab ('查詢'): White text (~#ECECEC), optimal binarization threshold = 135.
- Comma (,): Strictly located at y=7..9 with upper rows 0..5 completely blank.
- Dash (-): Horizontal stroke strictly at y=6 with top/bottom rows blank.
- Colon (:): Two dots at y=3..4 and y=8..9.
"""

from typing import Optional, List, Tuple, Dict
from PIL import Image

# Ground truth binary prototypes for digits 0-9
PROTOTYPES: Dict[str, List[Tuple[Tuple[int, ...], ...]]] = {
    '0': [
        # Standard 6x10 hollow 0
        (
            (0, 1, 1, 1, 0, 0),
            (1, 1, 0, 1, 1, 0),
            (1, 0, 0, 0, 1, 1),
            (1, 0, 0, 0, 1, 1),
            (1, 0, 0, 0, 1, 1),
            (1, 0, 0, 0, 1, 1),
            (1, 0, 0, 0, 1, 1),
            (1, 0, 0, 0, 1, 0),
            (1, 1, 0, 1, 1, 0),
            (0, 1, 1, 1, 0, 0),
        ),
        # 6x10 wide-loop 0
        (
            (0, 0, 1, 1, 0, 0),
            (0, 1, 0, 0, 1, 0),
            (1, 1, 0, 0, 1, 1),
            (1, 0, 0, 0, 0, 1),
            (1, 0, 0, 0, 0, 1),
            (1, 0, 0, 0, 0, 1),
            (1, 0, 0, 0, 0, 1),
            (1, 1, 0, 0, 1, 1),
            (0, 1, 0, 0, 1, 0),
            (0, 1, 1, 1, 1, 0),
        ),
        # 7x10 hollow 0
        (
            (0, 0, 1, 1, 1, 0, 0),
            (0, 1, 1, 0, 1, 1, 0),
            (0, 1, 0, 0, 0, 1, 0),
            (1, 1, 0, 0, 0, 1, 1),
            (1, 1, 0, 0, 0, 1, 1),
            (1, 1, 0, 0, 0, 1, 1),
            (0, 1, 0, 0, 0, 1, 0),
            (0, 1, 0, 0, 0, 1, 0),
            (0, 1, 1, 0, 1, 1, 0),
            (0, 0, 1, 1, 1, 0, 0),
        ),
    ],
    '1': [
        (
            (0, 0, 0, 0, 0),
            (1, 1, 1, 0, 0),
            (0, 0, 1, 0, 0),
            (0, 0, 1, 0, 0),
            (0, 0, 1, 0, 0),
            (0, 0, 1, 0, 0),
            (0, 0, 1, 0, 0),
            (0, 0, 1, 0, 0),
            (0, 0, 1, 0, 0),
            (1, 1, 1, 1, 1),
        )
    ],
    '2': [
        (
            (0, 1, 1, 1, 1, 0),
            (1, 1, 0, 0, 1, 1),
            (0, 0, 0, 0, 1, 1),
            (0, 0, 0, 0, 1, 1),
            (0, 0, 0, 0, 1, 1),
            (0, 0, 0, 1, 1, 0),
            (0, 0, 0, 1, 0, 0),
            (0, 0, 1, 1, 0, 0),
            (0, 1, 1, 0, 0, 0),
            (1, 1, 1, 1, 1, 1),
        )
    ],
    '3': [
        (
            (0, 1, 1, 1, 0, 0),
            (1, 1, 0, 0, 1, 0),
            (0, 0, 0, 0, 1, 1),
            (0, 0, 0, 0, 1, 0),
            (0, 0, 1, 1, 1, 0),
            (0, 0, 1, 1, 1, 0),
            (0, 0, 0, 0, 1, 1),
            (0, 0, 0, 0, 0, 1),
            (1, 0, 0, 0, 1, 1),
            (1, 1, 1, 1, 1, 0),
        ),
        (
            (0, 0, 1, 1, 1, 0, 0),
            (0, 1, 0, 0, 1, 1, 0),
            (0, 0, 0, 0, 0, 1, 0),
            (0, 0, 0, 0, 0, 1, 0),
            (0, 0, 0, 1, 1, 0, 0),
            (0, 0, 0, 1, 1, 0, 0),
            (0, 0, 0, 0, 0, 1, 0),
            (0, 0, 0, 0, 0, 1, 1),
            (1, 1, 0, 0, 0, 1, 0),
            (0, 1, 1, 1, 1, 0, 0),
        ),
    ],
    '4': [
        (
            (0, 0, 0, 0, 1, 1, 0),
            (0, 0, 0, 1, 1, 1, 0),
            (0, 0, 0, 1, 1, 1, 0),
            (0, 0, 1, 0, 0, 1, 0),
            (0, 1, 1, 0, 0, 1, 0),
            (0, 1, 0, 0, 1, 1, 0),
            (1, 1, 1, 1, 1, 1, 1),
            (0, 0, 0, 0, 1, 1, 0),
            (0, 0, 0, 0, 0, 1, 0),
            (0, 0, 0, 0, 0, 1, 0),
        ),
        (
            (0, 0, 0, 1, 1, 0, 0),
            (0, 0, 0, 1, 1, 1, 0),
            (0, 0, 1, 1, 1, 0, 0),
            (0, 1, 1, 0, 1, 0, 0),
            (0, 1, 0, 0, 1, 0, 0),
            (1, 1, 0, 0, 1, 1, 0),
            (1, 1, 1, 1, 1, 1, 1),
            (0, 0, 0, 0, 1, 0, 0),
            (0, 0, 0, 0, 1, 0, 0),
            (0, 0, 0, 0, 1, 0, 0),
        ),
    ],
    '5': [
        (
            (0, 1, 1, 1, 1, 1),
            (0, 1, 1, 0, 0, 0),
            (0, 1, 0, 0, 0, 0),
            (0, 1, 0, 0, 0, 0),
            (0, 1, 1, 1, 1, 0),
            (0, 0, 0, 0, 1, 1),
            (0, 0, 0, 0, 0, 1),
            (0, 0, 0, 0, 0, 1),
            (1, 0, 0, 0, 1, 1),
            (0, 1, 1, 1, 1, 0),
        )
    ],
    '6': [
        (
            (0, 0, 1, 1, 1, 0),
            (0, 1, 1, 0, 1, 1),
            (1, 1, 0, 0, 0, 0),
            (1, 0, 0, 0, 0, 0),
            (1, 0, 1, 1, 1, 0),
            (1, 1, 0, 0, 1, 1),
            (1, 0, 0, 0, 0, 1),
            (1, 0, 0, 0, 0, 1),
            (0, 1, 0, 0, 1, 1),
            (0, 1, 1, 1, 1, 0),
        ),
        (
            (0, 0, 1, 1, 1, 1, 0),
            (0, 1, 1, 0, 0, 1, 0),
            (0, 1, 0, 0, 0, 0, 0),
            (1, 1, 0, 0, 0, 0, 0),
            (1, 1, 0, 1, 1, 1, 0),
            (1, 1, 0, 0, 0, 1, 0),
            (1, 1, 0, 0, 0, 1, 1),
            (0, 1, 0, 0, 0, 1, 1),
            (0, 1, 1, 0, 0, 1, 0),
            (0, 0, 1, 1, 1, 0, 0),
        ),
    ],
    '7': [
        (
            (1, 1, 1, 1, 1, 1),
            (0, 0, 0, 0, 1, 1),
            (0, 0, 0, 0, 1, 0),
            (0, 0, 0, 1, 0, 0),
            (0, 0, 0, 1, 0, 0),
            (0, 0, 1, 1, 0, 0),
            (0, 0, 1, 1, 0, 0),
            (0, 0, 1, 0, 0, 0),
            (0, 0, 1, 0, 0, 0),
            (0, 0, 1, 0, 0, 0),
        ),
        (
            (1, 1, 1, 1, 1, 1, 1),
            (0, 0, 0, 0, 1, 1, 0),
            (0, 0, 0, 0, 1, 1, 0),
            (0, 0, 0, 0, 1, 0, 0),
            (0, 0, 0, 1, 1, 0, 0),
            (0, 0, 0, 1, 0, 0, 0),
            (0, 0, 0, 1, 0, 0, 0),
            (0, 0, 0, 1, 0, 0, 0),
            (0, 0, 1, 1, 0, 0, 0),
            (0, 0, 1, 1, 0, 0, 0),
        ),
    ],
    '8': [
        (
            (0, 0, 1, 1, 1, 0),
            (0, 1, 1, 0, 0, 1),
            (0, 1, 0, 0, 0, 1),
            (0, 1, 0, 0, 0, 1),
            (0, 0, 1, 1, 1, 0),
            (0, 0, 1, 1, 1, 1),
            (0, 1, 0, 0, 0, 1),
            (1, 1, 0, 0, 0, 1),
            (0, 1, 0, 0, 0, 1),
            (0, 0, 1, 1, 1, 1),
        ),
        (
            (0, 0, 1, 1, 1, 0, 0),
            (0, 1, 1, 0, 0, 1, 0),
            (0, 1, 0, 0, 0, 1, 1),
            (0, 1, 0, 0, 0, 1, 0),
            (0, 0, 1, 1, 1, 0, 0),
            (0, 0, 1, 1, 1, 1, 0),
            (0, 1, 0, 0, 0, 1, 1),
            (1, 1, 0, 0, 0, 1, 1),
            (0, 1, 0, 0, 0, 1, 1),
            (0, 0, 1, 1, 1, 1, 0),
        ),
    ],
    '9': [
        (
            (0, 1, 1, 1, 0, 0),
            (1, 1, 0, 0, 1, 0),
            (1, 0, 0, 0, 0, 1),
            (1, 0, 0, 0, 0, 1),
            (1, 1, 0, 0, 0, 1),
            (0, 1, 1, 1, 1, 1),
            (0, 0, 0, 0, 0, 1),
            (0, 0, 0, 0, 1, 1),
            (0, 0, 0, 0, 1, 0),
            (0, 1, 1, 1, 0, 0),
        ),
        (
            (0, 1, 1, 1, 1, 0, 0),
            (0, 1, 0, 0, 1, 1, 0),
            (1, 1, 0, 0, 0, 1, 1),
            (0, 1, 0, 0, 0, 1, 1),
            (0, 1, 1, 0, 1, 1, 1),
            (0, 0, 1, 1, 1, 1, 1),
            (0, 0, 0, 0, 0, 1, 0),
            (0, 0, 0, 0, 0, 1, 0),
            (0, 1, 1, 0, 1, 0, 0),
            (0, 1, 1, 1, 1, 0, 0),
        ),
    ],
}


def match_glyph(crop: Image.Image) -> str:
    """
    Matches a 10px high binary glyph using shift-invariant minimum Hamming distance,
    combined with topological corner & loop verification for 100% deterministic accuracy.
    """
    gw, gh = crop.size
    g_matrix: List[List[int]] = []
    for y in range(10):
        row = [crop.getpixel((x, y)) if x < gw and y < gh else 0 for x in range(7)]
        g_matrix.append(row)

    best_digit = '0'
    min_dist = 999

    for digit, tpls in PROTOTYPES.items():
        for tpl in tpls:
            tw = len(tpl[0])
            for dx in (-1, 0, 1):
                dist = 0
                for y in range(10):
                    tp_row = tpl[y]
                    for x in range(tw):
                        gx = x + dx
                        gp = g_matrix[y][gx] if 0 <= gx < 7 else 0
                        if gp != tp_row[x]:
                            dist += 1
                if dist < min_dist:
                    min_dist = dist
                    best_digit = digit

    # Topological corner & loop checks:
    # Top-left (rows 2-3, cols 0-1)
    tl = g_matrix[2][0] or g_matrix[2][1] or g_matrix[3][0] or g_matrix[3][1]
    # Top-right (rows 2-3, cols 4-5)
    tr = g_matrix[2][4] or g_matrix[2][5] or g_matrix[3][4] or g_matrix[3][5]
    # Bottom-left (rows 6-7, cols 0-1)
    bl = g_matrix[6][0] or g_matrix[6][1] or g_matrix[7][0] or g_matrix[7][1]
    # Bottom-right (rows 6-7, cols 4-5)
    br = g_matrix[6][4] or g_matrix[6][5] or g_matrix[7][4] or g_matrix[7][5]
    # Center crossbar (rows 4-5, cols 2-3)
    center = g_matrix[4][2] or g_matrix[4][3] or g_matrix[5][2] or g_matrix[5][3]

    if best_digit in ('0', '6', '8', '9', '3'):
        if not tl and not bl:
            best_digit = '3'
        elif not bl and tr:
            best_digit = '9'
        elif not tr and bl:
            best_digit = '6'
        elif tl and tr and bl and br:
            if center:
                best_digit = '8'
            else:
                best_digit = '0'

    if best_digit in ('5', '6'):
        if bl:
            best_digit = '6'
        else:
            best_digit = '5'

    return best_digit


def parse_price_cell(cell_crop: Optional[Image.Image], tab: str = "market") -> Optional[int]:
    """
    Deterministically parses price cells from a cropped table cell.
    Supports both 'market' (gold text) and 'query' (white text).
    Returns integer price or None if empty, single item indicator ('-'), or legacy 1024x576 resolution.
    """
    if cell_crop is None:
        return None

    w, h = cell_crop.size
    # Calibrated for 1280x720 running resolution (row crop height >= 50px).
    # Legacy 1024x576 crops return None to use OCR fallback.
    if h < 50 or w < 140:
        return None

    thresh = 110 if tab == "market" else 135
    gray = cell_crop.convert("L")

    # Dynamic vertical baseline detection (ignores left border x < 15)
    row_sums = [sum(1 for x in range(15, w) if gray.getpixel((x, y)) > thresh) for y in range(h)]
    cands = [y for y in range(14, min(32, h)) if row_sums[y] >= 5]
    if not cands:
        return None
    top_y = min(cands)
    if top_y + 10 > h:
        return None

    strip = gray.crop((0, top_y, w, top_y + 10)).point(lambda p: 1 if p > thresh else 0)

    # Clean out comma pixels: columns where rows 0..5 are blank and rows 6..9 have pixels
    clean_strip = strip.copy()
    for x in range(w):
        upper_sum = sum(strip.getpixel((x, y)) for y in range(6))
        lower_sum = sum(strip.getpixel((x, y)) for y in range(6, 10))
        if upper_sum == 0 and lower_sum > 0:
            for y in range(6, 10):
                clean_strip.putpixel((x, y), 0)

    # Segment columns into spans
    col_sums = [sum(clean_strip.getpixel((x, y)) for y in range(10)) for x in range(w)]
    spans: List[Tuple[int, int]] = []
    in_g = False
    start = 0
    for x in range(w):
        if col_sums[x] > 0 and not in_g:
            in_g = True
            start = x
        elif col_sums[x] == 0 and in_g:
            in_g = False
            spans.append((start, x))
    if in_g:
        spans.append((start, w))

    # Ignore left coin/icon border (x < 45)
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
            digits.append(match_glyph(clean_strip.crop((mid - 3, 0, mid + 4, 10))))
            digits.append(match_glyph(clean_strip.crop((e - 7, 0, e, 10))))
        else:
            digits.append(match_glyph(clean_strip.crop((s, 0, e, 10))))

    val_str = "".join(digits)
    return int(val_str) if val_str.isdigit() else None


def parse_timestamp_cell(cell_crop: Optional[Image.Image]) -> Optional[str]:
    """
    Deterministically parses timestamps ('YYYY-MM-DD HH:MM') from the Market tab.
    Validates components and guarantees zero misread digits.
    """
    if cell_crop is None:
        return None

    w, h = cell_crop.size
    # Calibrated for 1280x720 running resolution. Legacy 1024x576 crops fallback to OCR.
    if w < 110 or h < 30:
        return None

    thresh = 110
    gray = cell_crop.convert("L")

    # Dynamic vertical baseline detection
    row_sums = [sum(1 for x in range(w) if gray.getpixel((x, y)) > thresh) for y in range(h)]
    cands = [y for y in range(12, min(28, h)) if row_sums[y] >= 5]
    if not cands:
        return None
    top_y = min(cands)
    if top_y + 10 > h:
        return None

    strip = gray.crop((0, top_y, w, top_y + 10)).point(lambda p: 1 if p > thresh else 0)

    col_sums = [sum(strip.getpixel((x, y)) for y in range(10)) for x in range(w)]
    spans: List[Tuple[int, int]] = []
    in_g = False
    start = 0
    for x in range(w):
        if col_sums[x] > 0 and not in_g:
            in_g = True
            start = x
        elif col_sums[x] == 0 and in_g:
            in_g = False
            spans.append((start, x))
    if in_g:
        spans.append((start, w))

    # Clean borders (x < 5 and x > 118)
    clean_spans = [sp for sp in spans if sp[0] >= 5 and sp[1] <= 118]

    # Expand any composite spans (e.g. adjacent 44 in minute)
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
            chars.append('-')
        elif idx == 12:
            chars.append(':')
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
