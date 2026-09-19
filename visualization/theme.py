"""Theme styling, typography, color palettes, and financial formatting.

Provides centralized font caches, color constants, CJK price abbreviations
('億' / '萬'), and tick calculation algorithms for financial charts.
"""

import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import ImageDraw, ImageFont

from config.settings import FONT_GS_PATH, FONT_NOTO_PATH

# ==============================================================================
# Financial Color Palette (Dark Theme / Binance Professional)
# ==============================================================================
COLOR_BG = (11, 14, 20)
COLOR_CARD = (21, 26, 36)
COLOR_GRID = (27, 34, 48)
COLOR_UP = (0, 192, 135)
COLOR_DOWN = (246, 70, 93)
COLOR_ORANGE = (240, 185, 11)
COLOR_CYAN = (14, 203, 129)
COLOR_TEXT_WHITE = (234, 236, 239)
COLOR_TEXT_MUTED = (132, 142, 156)
COLOR_TEXT_SECONDARY = (183, 189, 198)

# Font Cache to maximize API throughput (~25ms rendering)
_FONT_CACHE: Dict[Tuple[str, int, str], ImageFont.FreeTypeFont] = {}


def get_font_gs(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    """Retrieves cached Google Sans Latin font at requested size and weight.

    Args:
        size: Font size in pixels.
        weight: 'Bold', 'Medium', or 'Regular'.

    Returns:
        FreeTypeFont instance.
    """
    key = ("gs", size, weight)
    if key not in _FONT_CACHE:
        f = ImageFont.truetype(str(FONT_GS_PATH), size)
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
        _FONT_CACHE[key] = f
    return _FONT_CACHE[key]


def get_font_noto(size: int) -> ImageFont.FreeTypeFont:
    """Retrieves cached Noto Sans TC Chinese font at requested size.

    Args:
        size: Font size in pixels.

    Returns:
        FreeTypeFont instance.
    """
    key = ("noto", size, "Medium")
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(str(FONT_NOTO_PATH), size)
    return _FONT_CACHE[key]


def format_price_cjk(num: Optional[float]) -> str:
    """Formats a number into concise Chinese financial notation (億 / 萬).

    Args:
        num: Numeric price value.

    Returns:
        Formatted price string (e.g. '2.5 億', '850 萬', '50,000').
    """
    if num is None:
        return "-"
    if abs(num) >= 100_000_000:
        v = num / 100_000_000
        formatted = f"{v:.2f}".rstrip("0").rstrip(".")
        return f"{formatted} 億"
    if abs(num) >= 10_000:
        v = num / 10_000
        return f"{v:.1f} 萬"
    return f"{int(num):,}"


def format_axis_price(val: float, is_badge: bool = False) -> str:
    """Formats price numbers into concise Chinese financial units for Y-axis.

    - 億 unit: allows decimal digits (e.g. 2.1 億, 4.59 億).
    - 萬 unit:
        - Y-axis grid ticks: clean integers with NO decimals (e.g. 300 萬, 280 萬).
        - Match line badge: allows 1 decimal place (e.g. 276.7 萬).

    Args:
        val: Numeric price value.
        is_badge: True if formatting for current price callout badge.

    Returns:
        Formatted price string.
    """
    if abs(val) >= 100_000_000:
        v = val / 100_000_000
        formatted = f"{v:.2f}".rstrip("0").rstrip(".")
        return f"{formatted} 億"
    if abs(val) >= 10_000:
        v = val / 10_000
        if not is_badge:
            return f"{int(round(v))} 萬"
        return f"{v:.1f} 萬"
    return f"{int(val):,}"


def format_vol_cjk(num: Optional[float]) -> str:
    """Formats traded quantity volume with unit suffix.

    Args:
        num: Volume count.

    Returns:
        Formatted string (e.g. '1,420 件').
    """
    if num is None or num == 0:
        return "0 件"
    return f"{int(num):,} 件"


def calc_nice_ticks(
    p_min: float, p_max: float, target_ticks: int = 5
) -> Tuple[List[int], float, float]:
    """Calculates clean, rounded financial numbers for the price Y-axis.

    Args:
        p_min: Minimum price.
        p_max: Maximum price.
        target_ticks: Desired number of grid ticks.

    Returns:
        Tuple of (tick_values_list, nice_minimum, nice_maximum).
    """
    raw_range = p_max - p_min
    if raw_range <= 0:
        val = int(p_min)
        return [val], float(val - 1), float(val + 1)

    raw_step = raw_range / target_ticks
    exponent = math.floor(math.log10(raw_step))
    fraction = raw_step / (10**exponent)

    if fraction < 1.4:
        nice_mult = 1
    elif fraction < 3.0:
        nice_mult = 2
    elif fraction < 7.0:
        nice_mult = 5
    else:
        nice_mult = 10

    step = nice_mult * (10**exponent)
    nice_min = math.floor(p_min / step) * step
    nice_max = math.ceil(p_max / step) * step

    ticks = []
    curr = nice_min
    while curr <= nice_max + step * 0.001:
        ticks.append(int(curr) if step >= 1 else round(curr, 2))
        curr += step
    return ticks, float(nice_min), float(nice_max)


def draw_text_mixed(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[float, float],
    text: str,
    font_latin: ImageFont.FreeTypeFont,
    font_cjk: ImageFont.FreeTypeFont,
    fill: Tuple[int, int, int],
    use_baseline: bool = True,
) -> float:
    """Draws mixed Latin/CJK string sequentially with font auto-selection.

    Args:
        draw: PIL ImageDraw instance.
        xy: (x, y) starting coordinate.
        text: String containing mixed ASCII and CJK characters.
        font_latin: Latin font.
        font_cjk: CJK font.
        fill: RGB color tuple.
        use_baseline: Whether to align using 'ls' baseline anchor.

    Returns:
        Total width of the drawn string in pixels.
    """
    x, y = xy
    orig_x = x
    anchor = "ls" if use_baseline else "lt"

    runs: List[Tuple[str, bool]] = []
    curr_run = ""
    curr_is_cjk: Optional[bool] = None

    for char in text:
        is_cjk = ord(char) > 0x7F
        if curr_is_cjk is None:
            curr_is_cjk = is_cjk
            curr_run = char
        elif is_cjk == curr_is_cjk:
            curr_run += char
        else:
            runs.append((curr_run, curr_is_cjk))
            curr_run = char
            curr_is_cjk = is_cjk
    if curr_run:
        runs.append((curr_run, curr_is_cjk if curr_is_cjk is not None else False))

    for run_text, is_cjk in runs:
        font = font_cjk if is_cjk else font_latin
        draw.text((x, y), run_text, font=font, fill=fill, anchor=anchor)
        w = draw.textlength(run_text, font=font)
        x += w

    return x - orig_x
