"""Backwards compatibility shim for legacy src.kline_plotter imports."""

from visualization.kline_plotter import (
    generate_kline_plot,
    generate_kline_plot_bytes,
    get_kline_data,
)
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

__all__ = [
    "generate_kline_plot",
    "generate_kline_plot_bytes",
    "get_kline_data",
    "format_price_cjk",
    "format_axis_price",
    "format_vol_cjk",
    "calc_nice_ticks",
    "get_font_gs",
    "get_font_noto",
    "draw_text_mixed",
    "measure_text_mixed",
]
