"""Financial candlestick renderer for Artale Market Tracker.

Renders 1800x2400 portrait candlestick charts with Google Sans
typography, Noto Sans TC Chinese rendering, dynamic Y-axis ticks, VWAP curves,
and UI badges.
"""

from datetime import datetime, timedelta
import io
import math
import os
from pathlib import Path
import sqlite3
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from config.settings import DB_PATH
from core.categories import classify_item_type
from core.watchlist import get_item_last_updated
from visualization.theme import (
    calc_nice_ticks,
    draw_text_mixed,
    format_axis_price,
    format_price_cjk,
    format_vol_cjk,
    get_font_gs,
    get_font_noto,
    measure_text_mixed,
)

def get_kline_data(item_name: str, timeframe: str = "1h", limit: int = 36, db_path: Optional[Path] = None) -> Tuple[List[Dict], Optional[int]]:
    active_db = db_path or DB_PATH
    with sqlite3.connect(active_db) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT bucket_time, open_price, high_price, low_price, close_price, volume, turnover, vwap, trade_count
            FROM kline_candles
            WHERE item_name = ? AND timeframe = ?
            ORDER BY bucket_time ASC
        """, (item_name, timeframe))
        rows = c.fetchall()

        c.execute("""
            SELECT min(unit_price) FROM active_listings
            WHERE item_name = ? AND unit_price >= 500
              AND replace(captured_at, 'T', ' ') >= (
                  SELECT datetime(replace(max(captured_at), 'T', ' '), '-30 minutes')
                  FROM active_listings WHERE item_name = ?
              )
        """, (item_name, item_name))
        ask_row = c.fetchone()
        lowest_ask = ask_row[0] if ask_row and ask_row[0] else None

    candles = []
    seen = set()
    for r in rows:
        t_str = r[0]
        if t_str in seen:
            continue
        seen.add(t_str)
        candles.append({
            "time": t_str,
            "open": r[1],
            "high": r[2],
            "low": r[3],
            "close": r[4],
            "volume": r[5],
            "turnover": r[6],
            "vwap": r[7],
            "trades": r[8] if len(r) > 8 else 0
        })

    return candles[-limit:], lowest_ask


def get_24h_summary(item_name: str, db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Calculates 24-hour market summary metrics from 1-hour candles.

    Evaluates across the 24 hourly buckets ending at the market's latest
    available candle timestamp.

    Args:
        item_name: Canonical item name.
        db_path: Optional custom path to SQLite database.

    Returns:
        Dict with keys: 'vol_24', 'turnover_24', 'high_24', 'low_24',
        'chg_24', 'vwap_24', 'latest_price'.
    """
    active_db = db_path or DB_PATH
    with sqlite3.connect(active_db) as conn:
        c = conn.cursor()
        c.execute("SELECT max(bucket_time) FROM kline_candles WHERE timeframe = '1h'")
        row = c.fetchone()
        if not row or not row[0]:
            return {
                "vol_24": 0,
                "turnover_24": 0,
                "high_24": 0,
                "low_24": 0,
                "chg_24": 0.0,
                "vwap_24": 0,
                "latest_price": 0,
            }

        max_dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        cutoff_str = (max_dt - timedelta(hours=23)).strftime("%Y-%m-%d %H:%M:%S")

        c.execute("""
            SELECT bucket_time, open_price, high_price, low_price, close_price, volume, turnover
            FROM kline_candles
            WHERE item_name = ? AND timeframe = '1h' AND bucket_time >= ?
            ORDER BY bucket_time ASC
        """, (item_name, cutoff_str))
        rows = c.fetchall()

        c.execute("""
            SELECT close_price, vwap FROM kline_candles
            WHERE item_name = ? AND timeframe = '1h'
            ORDER BY bucket_time DESC LIMIT 1
        """, (item_name,))
        latest_row = c.fetchone()
        latest_price = latest_row[0] if latest_row else 0
        latest_vwap = latest_row[1] if (latest_row and latest_row[1]) else latest_price

        if not rows:
            return {
                "vol_24": 0,
                "turnover_24": 0,
                "high_24": latest_price,
                "low_24": latest_price,
                "chg_24": 0.0,
                "vwap_24": latest_vwap,
                "latest_price": latest_price,
            }

        vol_24 = sum(r[5] for r in rows)
        turnover_24 = sum(r[6] for r in rows)
        high_24 = max(r[2] for r in rows)
        low_24 = min(r[3] for r in rows)
        open_24 = rows[0][1]
        close_latest = rows[-1][4]
        chg_24 = ((close_latest - open_24) / open_24 * 100) if open_24 else 0.0
        vwap_24 = int(round(turnover_24 / vol_24)) if vol_24 > 0 else close_latest

        return {
            "vol_24": vol_24,
            "turnover_24": turnover_24,
            "high_24": high_24,
            "low_24": low_24,
            "chg_24": chg_24,
            "vwap_24": vwap_24,
            "latest_price": close_latest,
        }


def draw_smooth_bubble(
    img: Image.Image,
    box: Tuple[float, float, float, float],
    radius: int,
    fill: Optional[Tuple[int, int, int, int]] = None,
    outline: Optional[Tuple[int, int, int, int]] = None,
    outline_w: int = 1,
    text: str = "",
    font_latin: Optional[ImageFont.FreeTypeFont] = None,
    font_cjk: Optional[ImageFont.FreeTypeFont] = None,
    text_color: Tuple[int, int, int, int] = (255, 255, 255, 255)
) -> None:
    """Renders an anti-aliased rounded rectangle with centered text.

    Uses 4x supersampling and Lanczos filtering for corners,
    with bounding-box text centering for Latin and CJK typography.
    """
    bx1, by1, bx2, by2 = [int(round(v)) for v in box]
    w = bx2 - bx1
    h = by2 - by1
    if w <= 0 or h <= 0:
        return

    # 4x supersampling for anti-aliased borders
    scale = 4
    sw, sh = w * scale, h * scale
    sr = radius * scale
    swidth = outline_w * scale

    bubble = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    if fill:
        mask = Image.new("L", (sw, sh), 0)
        mdr = ImageDraw.Draw(mask)
        mdr.rounded_rectangle((0, 0, sw, sh), radius=sr, fill=255)
        mask = mask.resize((w, h), Image.Resampling.LANCZOS)
        fill_layer = Image.new("RGBA", (w, h), fill)
        bubble.paste(fill_layer, (0, 0), mask)

    if outline and outline_w > 0:
        mask_out = Image.new("L", (sw, sh), 0)
        mdr_out = ImageDraw.Draw(mask_out)
        mdr_out.rounded_rectangle((0, 0, sw, sh), radius=sr, outline=255, width=swidth)
        mask_out = mask_out.resize((w, h), Image.Resampling.LANCZOS)
        out_layer = Image.new("RGBA", (w, h), outline)
        bubble.paste(out_layer, (0, 0), mask_out)

    img.paste(bubble, (bx1, by1), bubble)

    # Bounding-box text centering
    if text and font_latin and font_cjk:
        scratch = Image.new("RGBA", (max(w * 2, 600), max(h * 2, 200)), (0, 0, 0, 0))
        sdr = ImageDraw.Draw(scratch)
        draw_text_mixed(sdr, (30, 90), text, font_latin, font_cjk, text_color, use_baseline=True)
        bbox = scratch.getbbox()
        if bbox:
            ink = scratch.crop(bbox)
            iw, ih = ink.size
            px = bx1 + int(round((w - iw) / 2.0))
            py = by1 + int(round((h - ih) / 2.0))
            img.paste(ink, (px, py), ink)

def generate_kline_plot(
    item_name: str,
    timeframe: str = "1h",
    width: int = 1800,
    height: int = 2400,
    output_path: Optional[str] = None,
    db_path: Optional[Path] = None
) -> Image.Image:
    """
    Renders an ultra-high-resolution 3:4 portrait (default 1800x2400) financial candlestick chart
    with silky-smooth anti-aliased tab borders, optical text centering, and Google Sans typography.
    """
    candles, lowest_ask = get_kline_data(item_name, timeframe=timeframe, limit=36, db_path=db_path)
    if not candles:
        raise ValueError(f"No candlestick data available for '{item_name}' on timeframe '{timeframe}'.")

    # Scaling ratio relative to baseline 1200x1600 layout
    sx = width / 1200.0
    sy = height / 1600.0

    # ==========================================
    # High-Legibility Professional Type Hierarchy
    # ==========================================
    font_price = get_font_gs(round(72 * sx), "Bold")
    font_title_latin = get_font_gs(round(44 * sx), "Bold")
    font_title_cjk = get_font_noto(round(42 * sx))

    font_badge_latin = get_font_gs(round(24 * sx), "Bold")
    font_badge_cjk = get_font_noto(round(22 * sx))

    font_metric_val = get_font_gs(round(30 * sx), "Bold")
    font_metric_cjk_val = get_font_noto(round(28 * sx))
    font_metric_lbl = get_font_noto(round(19 * sx))

    font_toolbar_lbl = get_font_gs(round(22 * sx), "Bold")
    font_toolbar_cjk = get_font_noto(round(21 * sx))

    font_axis = get_font_gs(round(29 * sx), "Bold")
    font_axis_cjk = get_font_noto(round(28 * sx))
    font_axis_time = get_font_gs(round(22 * sx), "Bold")

    font_footer_reg = get_font_gs(round(20 * sx), "Regular")
    font_footer_bold = get_font_gs(round(20 * sx), "Bold")

    # Color Palette (Dark Theme)
    C_BG = (11, 14, 20, 255)             # #0b0e14 Deep Canvas
    C_CARD = (18, 22, 30, 255)           # #12161e Card Background
    C_CARD_SUB = (24, 28, 38, 255)       # #181c26 Sub-card
    C_BORDER = (38, 44, 56, 255)         # #262c38 Primary Border
    C_GRID = (25, 30, 42, 255)           # #191e2a Grid Lines
    C_AXIS_BG = (14, 18, 25, 255)        # #0e1219 Right Axis Strip

    C_TEXT_MAIN = (240, 242, 245, 255)   # #f0f2f5 Primary White
    C_TEXT_SUB = (140, 150, 166, 255)    # #8c96a6 Secondary Grey
    C_TEXT_DIM = (105, 115, 130, 255)    # #697382 Dim Muted

    C_UP = (14, 203, 129, 255)           # #0ecb81 Bullish Green
    C_DOWN = (246, 70, 93, 255)          # #f6465d Bearish Red
    C_GOLD = (240, 185, 11, 255)         # #f0b90b MA(7)
    C_BLUE = (41, 98, 255, 255)          # #2962ff MA(25)
    C_ASK = (255, 152, 0, 255)           # #ff9800 Lowest Ask

    # RGBA image for flawless anti-aliased layer composite
    img = Image.new("RGBA", (width, height), C_BG)
    draw = ImageDraw.Draw(img)

    # ==========================================
    # 1. Executive Summary Header Card
    # ==========================================
    header_h = round(300 * sy)
    draw.rectangle([(0, 0), (width, header_h)], fill=C_CARD)
    draw.line([(0, header_h), (width, header_h)], fill=C_BORDER, width=max(1, round(1 * sy)))

    # Row 1 (Title + Category Pill + Timeframe Tabs)
    title_baseline = round(58 * sy)
    margin_x = round(36 * sx)
    title_w = draw_text_mixed(draw, (margin_x, title_baseline), item_name, font_title_latin, font_title_cjk, C_TEXT_MAIN[:3], use_baseline=True)

    # Item Category Pill (Smooth rounded anti-aliased)
    cat_name = classify_item_type(item_name)
    cat_w = draw.textlength(cat_name, font=font_badge_cjk)
    cat_x = margin_x + title_w + round(18 * sx)
    cat_box = (cat_x, round(22 * sy), cat_x + cat_w + round(26 * sx), round(64 * sy))
    draw_smooth_bubble(
        img, cat_box, radius=round(8 * sx),
        fill=(28, 34, 46, 255), outline=C_BORDER, outline_w=1,
        text=cat_name, font_latin=font_badge_latin, font_cjk=font_badge_cjk,
        text_color=C_TEXT_SUB
    )

    # Timeframe Tab Selector (Right-aligned, silky-smooth borders)
    tf_tabs = [("1小時", "1h"), ("4小時", "4h"), ("日線", "1d")]
    tab_x = width - margin_x
    for label, tf_key in reversed(tf_tabs):
        is_active = (tf_key == timeframe)
        t_w = draw.textlength(label, font=font_badge_cjk)
        btn_w = t_w + round(32 * sx)
        tab_x -= btn_w
        tab_box = (tab_x, round(22 * sy), tab_x + btn_w, round(64 * sy))
        if is_active:
            draw_smooth_bubble(
                img, tab_box, radius=round(8 * sx),
                fill=(38, 48, 68, 255), outline=C_GOLD, outline_w=max(1, round(1.5 * sx)),
                text=label, font_latin=font_badge_latin, font_cjk=font_badge_cjk,
                text_color=C_GOLD
            )
        else:
            draw_smooth_bubble(
                img, tab_box, radius=round(8 * sx),
                fill=C_CARD_SUB, outline=C_BORDER, outline_w=1,
                text=label, font_latin=font_badge_latin, font_cjk=font_badge_cjk,
                text_color=C_TEXT_DIM
            )
        tab_x -= round(12 * sx)

    # Row 2: Hero Price + Change Pill + Lowest Ask Pill
    sum24 = get_24h_summary(item_name, db_path=db_path)
    latest_close = sum24["latest_price"] or candles[-1]["close"]
    chg_pct = sum24["chg_24"]
    c_chg = C_UP if chg_pct >= 0 else C_DOWN
    chg_sign = "+" if chg_pct >= 0 else ""

    price_str = f"{latest_close:,}"
    price_baseline = round(148 * sy)
    draw.text((margin_x, price_baseline), price_str, font=font_price, fill=C_TEXT_MAIN[:3], anchor="ls")
    price_w = draw.textlength(price_str, font=font_price)

    # 24H Change Pill
    chg_str = f"{chg_sign}{chg_pct:.2f}%"
    chg_w = draw.textlength(chg_str, font=font_badge_latin)
    pill_x = margin_x + price_w + round(20 * sx)
    pill_box = (pill_x, round(102 * sy), pill_x + chg_w + round(26 * sx), round(152 * sy))
    draw_smooth_bubble(
        img, pill_box, radius=round(8 * sx),
        fill=(c_chg[0]//6, c_chg[1]//6, c_chg[2]//6, 255),
        text=chg_str, font_latin=font_badge_latin, font_cjk=font_badge_cjk,
        text_color=c_chg
    )

    # Lowest Ask Pill (Right-aligned)
    if lowest_ask:
        ask_val_str = f"{lowest_ask:,}"
        ask_full = f"即時最低賣價  {ask_val_str}"
        ask_w = measure_text_mixed(draw, ask_full, font_badge_latin, font_badge_cjk)
        ask_box_x = width - ask_w - round(56 * sx)
        ask_box = (ask_box_x, round(102 * sy), width - margin_x, round(152 * sy))
        draw_smooth_bubble(
            img, ask_box, radius=round(8 * sx),
            fill=(42, 28, 10, 255), outline=C_ASK, outline_w=1,
            text=ask_full, font_latin=font_badge_latin, font_cjk=font_badge_cjk,
            text_color=C_ASK
        )

    # Row 3: 5-Column Financial Metrics Ribbon
    vwap_val = sum24["vwap_24"] or latest_close
    metrics = [
        ("24小時最高", f"{sum24['high_24']:,}" if sum24["high_24"] else "--"),
        ("24小時最低", f"{sum24['low_24']:,}" if sum24["low_24"] else "--"),
        ("24小時成交量", format_vol_cjk(sum24["vol_24"])),
        ("24小時成交額", format_price_cjk(sum24["turnover_24"])),
        ("加權均價 (VWAP)", f"{vwap_val:,}" if vwap_val else "--"),
    ]

    col_spacing = (width - margin_x * 2) // len(metrics)
    for idx, (lbl, val) in enumerate(metrics):
        mx = margin_x + idx * col_spacing
        draw.text((mx, round(195 * sy)), lbl, font=font_metric_lbl, fill=C_TEXT_SUB[:3])
        draw_text_mixed(draw, (mx, round(266 * sy)), val, font_metric_val, font_metric_cjk_val, C_TEXT_MAIN[:3], use_baseline=True)

    # ==========================================
    # 2. Indicator Toolbar Strip
    # ==========================================
    bar_y1 = round(300 * sy)
    bar_y2 = round(365 * sy)
    draw.rectangle([(0, bar_y1), (width, bar_y2)], fill=C_CARD_SUB)
    draw.line([(0, bar_y2), (width, bar_y2)], fill=C_BORDER, width=1)

    # Calculate Moving Averages
    closes = [c["close"] for c in candles]
    def calc_ma(period):
        res = []
        for i in range(len(closes)):
            if i < period - 1:
                res.append(None)
            else:
                res.append(sum(closes[i - period + 1 : i + 1]) / period)
        return res

    ma7 = calc_ma(7)
    ma25 = calc_ma(25)

    ind_x = margin_x
    mid_ind_y = (bar_y1 + bar_y2) // 2
    dot_r = round(6 * sx)

    # MA7 Dot & Text
    draw.ellipse([(ind_x, mid_ind_y - dot_r), (ind_x + dot_r * 2, mid_ind_y + dot_r)], fill=C_GOLD[:3])
    ma7_txt = f"MA(7): {ma7[-1]:,.0f}" if ma7[-1] else "MA(7): -"
    draw.text((ind_x + dot_r * 2 + round(10 * sx), round(320 * sy)), ma7_txt, font=font_toolbar_lbl, fill=C_GOLD[:3])
    ind_x += draw.textlength(ma7_txt, font=font_toolbar_lbl) + round(60 * sx)

    # MA25 Dot & Text
    draw.ellipse([(ind_x, mid_ind_y - dot_r), (ind_x + dot_r * 2, mid_ind_y + dot_r)], fill=C_BLUE[:3])
    ma25_txt = f"MA(25): {ma25[-1]:,.0f}" if ma25[-1] else "MA(25): -"
    draw.text((ind_x + dot_r * 2 + round(10 * sx), round(320 * sy)), ma25_txt, font=font_toolbar_lbl, fill=C_BLUE[:3])

    # ==========================================
    # 3. Main Candlestick Chart Area
    # ==========================================
    margin_left = margin_x
    axis_width = round(145 * sx)
    margin_right = axis_width
    chart_top = round(385 * sy)
    chart_bottom = round(1260 * sy)
    vol_top = round(1305 * sy)
    vol_bottom = round(1450 * sy)

    chart_w = width - margin_left - margin_right
    chart_h = chart_bottom - chart_top
    vol_h = vol_bottom - vol_top

    # Right Axis Background Strip
    draw.rectangle([(width - axis_width, bar_y2), (width, round(1530 * sy))], fill=C_AXIS_BG)
    draw.line([(width - axis_width, bar_y2), (width - axis_width, round(1530 * sy))], fill=C_BORDER, width=1)

    # Vertical Bounds with Nice Numbers
    chart_low = min(c["low"] for c in candles)
    chart_high = max(c["high"] for c in candles)
    raw_min = chart_low * 0.985
    raw_max = chart_high * 1.015
    if lowest_ask:
        raw_min = min(raw_min, lowest_ask * 0.99)
        raw_max = max(raw_max, lowest_ask * 1.01)

    nice_ticks, price_min, price_max = calc_nice_ticks(raw_min, raw_max, target_ticks=5)
    price_range = price_max - price_min if price_max > price_min else 1.0

    def y_price(p):
        return chart_bottom - ((p - price_min) / price_range) * chart_h

    ask_y = y_price(lowest_ask) if lowest_ask else -999

    # Horizontal Price Grid Lines & Labels
    axis_text_right = width - round(16 * sx)
    for g_val in nice_ticks:
        gy = y_price(g_val)
        draw.line([(margin_left, gy), (width - margin_right, gy)], fill=C_GRID[:3], width=1)

        # Avoid label collision with Lowest Ask badge
        if lowest_ask and price_min <= lowest_ask <= price_max and abs(gy - ask_y) < round(38 * sy):
            continue
        g_lbl = format_axis_price(g_val)
        lbl_w = measure_text_mixed(draw, g_lbl, font_axis, font_axis_cjk)
        draw_text_mixed(draw, (axis_text_right - lbl_w, gy + round(10 * sy)), g_lbl, font_axis, font_axis_cjk, C_TEXT_SUB[:3], use_baseline=True)

    # Lowest Ask Reference Line across chart
    if lowest_ask and price_min <= lowest_ask <= price_max:
        badge_x1 = width - margin_right + round(4 * sx)
        badge_x2 = width - round(6 * sx)
        curr_x = margin_left
        step_x = round(20 * sx)
        dash_len = round(10 * sx)
        while curr_x < badge_x1:
            draw.line([(curr_x, ask_y), (min(curr_x + dash_len, badge_x1), ask_y)], fill=C_ASK[:3], width=max(1, round(1.5 * sx)))
            curr_x += step_x

        # Solid Orange Price Badge on Right Axis (smooth & centered)
        badge_lbl = format_axis_price(lowest_ask, is_badge=True)
        b_half_h = round(24 * sy)
        badge_box = (badge_x1, ask_y - b_half_h, badge_x2, ask_y + b_half_h)
        draw_smooth_bubble(
            img, badge_box, radius=round(7 * sx),
            fill=C_ASK,
            text=badge_lbl, font_latin=font_axis, font_cjk=font_axis_cjk,
            text_color=(20, 10, 0, 255)
        )

    # Candles & Volume Bars
    n = len(candles)
    col_w = chart_w / n
    body_w = max(8, int(col_w * 0.70))
    wick_w = max(2, round(2 * sx))
    max_vol = max((c["volume"] for c in candles), default=1)
    if max_vol == 0:
        max_vol = 1

    cand_centers = []
    for idx, c in enumerate(candles):
        cx = margin_left + (idx + 0.5) * col_w
        cand_centers.append(cx)

        o = c["open"]
        h = c["high"]
        l = c["low"]
        cl = c["close"]
        v = c["volume"]

        is_up = cl >= o
        c_bar = C_UP[:3] if is_up else C_DOWN[:3]

        # Wick Line
        hy = y_price(h)
        ly = y_price(l)
        draw.line([(cx, hy), (cx, ly)], fill=c_bar, width=wick_w)

        # Body Rectangle
        oy = y_price(o)
        cly = y_price(cl)
        top_y = min(oy, cly)
        bot_y = max(oy, cly)
        if bot_y - top_y < 2:
            bot_y = top_y + 2

        bx1 = cx - body_w // 2
        bx2 = cx + body_w // 2
        draw.rectangle([(bx1, top_y), (bx2, bot_y)], fill=c_bar)

        # Volume Bar
        vh_px = (v / max_vol) * (vol_h - round(32 * sy))
        vy1 = vol_bottom - vh_px
        vy2 = vol_bottom
        draw.rectangle([(bx1, vy1), (bx2, vy2)], fill=c_bar)

    # Moving Average Lines
    for ma_vals, ma_col in [(ma7, C_GOLD[:3]), (ma25, C_BLUE[:3])]:
        pts = [(cand_centers[i], y_price(v)) for i, v in enumerate(ma_vals) if v is not None]
        if len(pts) > 1:
            for p1, p2 in zip(pts[:-1], pts[1:]):
                draw.line([p1, p2], fill=ma_col, width=max(2, round(3 * sx)))

    # ==========================================
    # 4. Volume Sub-chart Toolbar & Separator
    # ==========================================
    vol_sep_y = vol_top - round(15 * sy)
    draw.line([(0, vol_sep_y), (width, vol_sep_y)], fill=C_BORDER[:3], width=1)
    vol_lbl = f"成交量 (Volume)  {candles[-1]['volume']:,}"
    draw_text_mixed(draw, (margin_left, vol_top + round(16 * sy)), vol_lbl, font_toolbar_lbl, font_toolbar_cjk, C_TEXT_SUB[:3], use_baseline=True)
    vol_max_str = f"{int(max_vol):,}"
    vol_w = draw.textlength(vol_max_str, font=font_axis)
    draw.text((axis_text_right - vol_w, vol_top - round(4 * sy)), vol_max_str, font=font_axis, fill=C_TEXT_DIM[:3])
    draw.text((axis_text_right - draw.textlength("0", font=font_axis), vol_bottom - round(24 * sy)), "0", font=font_axis, fill=C_TEXT_DIM[:3])

    # ==========================================
    # 5. Bottom Time Axis
    # ==========================================
    time_sep_y = vol_bottom + round(10 * sy)
    draw.line([(0, time_sep_y), (width, time_sep_y)], fill=C_BORDER[:3], width=1)
    target_ticks = 5
    if n <= target_ticks:
        indices = list(range(n))
    else:
        indices = sorted(list(set(int(round(i * (n - 1) / (target_ticks - 1))) for i in range(target_ticks))))

    for i_pos, idx in enumerate(indices):
        cx = cand_centers[idx]
        t_raw = candles[idx]["time"]
        try:
            dt = datetime.strptime(t_raw, "%Y-%m-%d %H:%M:%S")
            t_label = dt.strftime("%m/%d %H:%M") if timeframe in ("1h", "4h") else dt.strftime("%Y/%m/%d")
        except Exception:
            t_label = t_raw[-8:]
        lbl_w = draw.textlength(t_label, font=font_axis_time)

        # Clamp to chart boundaries
        if i_pos == 0:
            tx = margin_left
        elif i_pos == len(indices) - 1:
            tx = width - margin_right - lbl_w
        else:
            tx = cx - lbl_w / 2
            if tx < margin_left + round(10 * sx):
                tx = margin_left + round(10 * sx)
            elif tx + lbl_w > width - margin_right - round(10 * sx):
                tx = width - margin_right - lbl_w - round(10 * sx)

        draw.text((tx, vol_bottom + round(22 * sy)), t_label, font=font_axis_time, fill=C_TEXT_SUB[:3])

    # ==========================================
    # 6. Full-Width Footer Strip
    # ==========================================
    footer_top = round(1535 * sy)
    draw.rectangle([(0, footer_top), (width, height)], fill=C_CARD)
    draw.line([(0, footer_top), (width, footer_top)], fill=C_BORDER[:3], width=1)

    mid_footer_y = footer_top + (height - footer_top) // 2
    baseline_y = footer_top + round(39 * sy)

    # Status Dot (Emerald Green)
    dot_cx = margin_left + round(6 * sx)
    dot_radius = round(6 * sx)
    draw.ellipse([(dot_cx - dot_radius, mid_footer_y - dot_radius), (dot_cx + dot_radius, mid_footer_y + dot_radius)], fill=C_UP[:3])

    # Left: Last Updated: timestamp from items_watchlist.json
    cur_x = dot_cx + round(18 * sx)
    draw.text((cur_x, baseline_y), "Last Updated: ", font=font_footer_reg, fill=C_TEXT_SUB[:3], anchor="ls")
    cur_x += draw.textlength("Last Updated: ", font=font_footer_reg)
    ts_str = get_item_last_updated(item_name)
    draw.text((cur_x, baseline_y), ts_str, font=font_footer_bold, fill=C_TEXT_MAIN[:3], anchor="ls")

    # Right: © 2026 By G8G
    c_prefix = f"© {datetime.now().year} By "
    c_author = "G8G"
    w_prefix = draw.textlength(c_prefix, font=font_footer_reg)
    w_author = draw.textlength(c_author, font=font_footer_bold)
    rx = width - margin_left - w_prefix - w_author

    draw.text((rx, baseline_y), c_prefix, font=font_footer_reg, fill=C_TEXT_SUB[:3], anchor="ls")
    draw.text((rx + w_prefix, baseline_y), c_author, font=font_footer_bold, fill=C_TEXT_MAIN[:3], anchor="ls")

    # Convert to RGB
    final_img = img.convert("RGB")

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        final_img.save(output_path, format="PNG", optimize=True)

    return final_img

def generate_kline_plot_bytes(
    item_name: str,
    timeframe: str = "1h",
    width: int = 1800,
    height: int = 2400,
    db_path: Optional[Path] = None
) -> bytes:
    """Generates PNG image bytes in memory without disk I/O."""
    img = generate_kline_plot(item_name, timeframe=timeframe, width=width, height=height, db_path=db_path)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

if __name__ == "__main__":
    for item in ["力量水晶", "楓葉祝福 20", "敏捷水晶"]:
        out = f"scratch/kline_rendered_{item}_1800x2400.png"
        generate_kline_plot(item, timeframe="1h", width=1800, height=2400, output_path=out)
        print(f"Generated {out}")
