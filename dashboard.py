import sqlite3
import json
import webbrowser
import calendar
from datetime import datetime
from pathlib import Path
from typing import List, Dict

DB_PATH = Path(__file__).resolve().parent / "data" / "market.db"
OUTPUT_HTML = Path(__file__).resolve().parent / "dashboard.html"
DOCS_DIR = Path(__file__).resolve().parent / "docs"
DOCS_HTML = DOCS_DIR / "index.html"

def export_dashboard_data() -> Dict:
    """
    Extracts all candles and active listings from market.db formatted for TradingView Lightweight Charts.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # 1. Fetch available canonical items from watchlist
        watchlist_file = Path(__file__).resolve().parent / "items_watchlist.json"
        if watchlist_file.exists():
            with open(watchlist_file, "r", encoding="utf-8") as f:
                items = sorted(json.load(f))
        else:
            cursor.execute("SELECT DISTINCT item_name FROM kline_candles")
            items = sorted([r[0] for r in cursor.fetchall()])

        data_by_item = {}
        for item in items:
            data_by_item[item] = {"1h": [], "4h": [], "1d": [], "lowest_ask": None}
            
            # Fetch lowest ask
            cursor.execute("SELECT min(unit_price) FROM active_listings WHERE item_name = ? AND unit_price > 0", (item,))
            ask_row = cursor.fetchone()
            data_by_item[item]["lowest_ask"] = ask_row[0] if ask_row and ask_row[0] else None

            # Fetch candles for each timeframe
            for tf in ["1h", "4h", "1d"]:
                cursor.execute("""
                    SELECT bucket_time, open_price, high_price, low_price, close_price, volume, turnover, vwap
                    FROM kline_candles
                    WHERE item_name = ? AND timeframe = ?
                    ORDER BY bucket_time ASC
                """, (item, tf))
                rows = cursor.fetchall()
                seen = set()
                for r in rows:
                    raw_t = r[0]
                    try:
                        # Use calendar.timegm so Lightweight Charts UTC getters render the exact game clock hour (e.g. 17:00, 18:00, 19:00) without 8-hour timezone shift
                        t_val = int(calendar.timegm(datetime.strptime(raw_t, "%Y-%m-%d %H:%M:%S").timetuple()))
                    except Exception:
                        t_val = raw_t
                    if t_val in seen:
                        continue
                    seen.add(t_val)
                    data_by_item[item][tf].append({
                        "time": t_val,
                        "open": r[1],
                        "high": r[2],
                        "low": r[3],
                        "close": r[4],
                        "volume": r[5],
                        "vwap": r[7]
                    })

    return {"items": items, "data": data_by_item}

def generate_dashboard_html():
    """
    Renders an interactive TradingView-style financial dashboard into dashboard.html.
    """
    # Read local standalone lightweight-charts JS
    js_path = Path(__file__).resolve().parent / "lightweight-charts.standalone.js"
    if js_path.exists():
        with open(js_path, "r", encoding="utf-8") as f:
            js_code = f.read()
    else:
        js_code = ""

    payload = export_dashboard_data()
    json_str = json.dumps(payload, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Artale Market</title>
    <script>{js_code}</script>
    <style>
        :root {{
            --bg-main: #131722;
            --bg-card: #1e222d;
            --bg-hover: #2a2e39;
            --border-color: #2a2e39;
            --text-main: #d1d4dc;
            --text-sub: #787b86;
            --accent-blue: #2962ff;
            --c-up: #26a69a;
            --c-down: #ef5350;
            --c-ask: #ff9800;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            -webkit-tap-highlight-color: transparent;
        }}

        html, body {{
            height: 100%;
            height: 100dvh;
            background-color: var(--bg-main);
            color: var(--text-main);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            user-select: none;
            -webkit-user-select: none;
        }}

        /* Header Navigation */
        header {{
            background-color: var(--bg-card);
            padding: 10px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            border-bottom: 1px solid var(--border-color);
            flex-shrink: 0;
        }}

        .header-main {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}

        .logo {{
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--accent-blue);
            display: flex;
            align-items: center;
            gap: 6px;
            white-space: nowrap;
        }}

        .header-controls {{
            display: flex;
            align-items: center;
            gap: 12px;
            flex: 1;
            justify-content: flex-end;
        }}

        .header-select {{
            flex: 1;
            max-width: 320px;
        }}

        select {{
            width: 100%;
            background-color: #2a2e39;
            color: var(--text-main);
            border: 1px solid #363c4e;
            padding: 7px 12px;
            border-radius: 6px;
            font-size: 0.88rem;
            font-weight: 500;
            outline: none;
            cursor: pointer;
            appearance: none;
            background-image: url('data:image/svg+xml;utf8,<svg fill="%23d1d4dc" height="24" viewBox="0 0 24 24" width="24" xmlns="http://www.w3.org/2000/svg"><path d="M7 10l5 5 5-5z"/></svg>');
            background-repeat: no-repeat;
            background-position: right 8px center;
            background-size: 18px;
            padding-right: 30px;
        }}

        select:focus {{
            border-color: var(--accent-blue);
        }}

        .tf-group {{
            display: inline-flex;
            background-color: #131722;
            border-radius: 6px;
            padding: 2px;
            border: 1px solid #2a2e39;
            flex-shrink: 0;
        }}

        .btn-tf {{
            background: transparent;
            color: var(--text-sub);
            border: none;
            padding: 5px 12px;
            border-radius: 4px;
            font-size: 0.82rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
        }}

        .btn-tf:hover {{
            color: var(--text-main);
        }}

        .btn-tf.active {{
            background-color: var(--accent-blue);
            color: #ffffff;
        }}

        /* Financial Metrics Strip */
        .metric-bar {{
            background-color: #161922;
            padding: 8px 16px;
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 12px;
            border-bottom: 1px solid var(--border-color);
            flex-shrink: 0;
        }}

        .metric {{
            display: flex;
            flex-direction: column;
            gap: 2px;
            min-width: 0;
        }}

        .metric-label {{
            color: var(--text-sub);
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .metric-val {{
            font-weight: 700;
            font-size: 0.96rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            font-variant-numeric: tabular-nums;
        }}

        .c-up {{ color: var(--c-up); }}
        .c-down {{ color: var(--c-down); }}
        .c-ask {{ color: var(--c-ask); }}

        /* Chart Canvas */
        #chart-container {{
            flex: 1;
            position: relative;
            width: 100%;
            min-height: 0;
            touch-action: pan-y pinch-zoom;
        }}

        /* Responsive Mobile Layout (<= 768px) */
        @media (max-width: 768px) {{
            header {{
                flex-direction: column;
                align-items: stretch;
                padding: 8px 12px;
                gap: 8px;
            }}

            .header-main {{
                justify-content: space-between;
                width: 100%;
            }}

            .header-controls {{
                width: 100%;
                justify-content: stretch;
            }}

            .header-select {{
                max-width: 100%;
                width: 100%;
            }}

            select {{
                padding: 8px 12px;
                font-size: 0.92rem;
            }}

            .metric-bar {{
                grid-template-columns: repeat(3, 1fr);
                gap: 6px 10px;
                padding: 6px 12px;
            }}

            .metric-label {{
                font-size: 0.65rem;
            }}

            .metric-val {{
                font-size: 0.88rem;
            }}
        }}

        @media (max-width: 380px) {{
            .metric-bar {{
                grid-template-columns: repeat(3, 1fr);
                gap: 4px 6px;
                padding: 4px 8px;
            }}
            .metric-label {{
                font-size: 0.6rem;
            }}
            .metric-val {{
                font-size: 0.8rem;
            }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="header-main">
            <div class="logo">
                <span>🍁</span> <span class="logo-title">Artale Market</span>
            </div>
            <div class="tf-group">
                <button class="btn-tf active" data-tf="1h">1H</button>
                <button class="btn-tf" data-tf="4h">4H</button>
                <button class="btn-tf" data-tf="1d">1D</button>
            </div>
        </div>
        <div class="header-controls">
            <div class="header-select">
                <select id="item-selector"></select>
            </div>
        </div>
    </header>

    <div class="metric-bar">
        <div class="metric">
            <span class="metric-label">最新成交 (Close)</span>
            <span class="metric-val" id="val-close">--</span>
        </div>
        <div class="metric">
            <span class="metric-label">最低掛賣 (Lowest Ask)</span>
            <span class="metric-val c-ask" id="val-ask">--</span>
        </div>
        <div class="metric">
            <span class="metric-label">買賣價差 (Spread)</span>
            <span class="metric-val" id="val-spread">--</span>
        </div>
        <div class="metric">
            <span class="metric-label">成交均價 (VWAP)</span>
            <span class="metric-val" id="val-vwap">--</span>
        </div>
        <div class="metric">
            <span class="metric-label">成交量 (Volume)</span>
            <span class="metric-val" id="val-vol">--</span>
        </div>
        <div class="metric">
            <span class="metric-label">區間最高/低 (H/L)</span>
            <span class="metric-val" id="val-range">--</span>
        </div>
    </div>

    <div id="chart-container"></div>

    <script>
        const payload = {json_str};
        const items = payload.items;
        const allData = payload.data;

        let currentItem = items[0] || "";
        let currentTf = "1h";

        // DOM elements
        const selector = document.getElementById("item-selector");
        const chartContainer = document.getElementById("chart-container");
        const valClose = document.getElementById("val-close");
        const valAsk = document.getElementById("val-ask");
        const valSpread = document.getElementById("val-spread");
        const valVwap = document.getElementById("val-vwap");
        const valVol = document.getElementById("val-vol");
        const valRange = document.getElementById("val-range");

        // Populate item selector
        items.forEach(it => {{
            const opt = document.createElement("option");
            opt.value = it;
            opt.textContent = it;
            selector.appendChild(opt);
        }});

        const isMobile = window.innerWidth <= 768;

        // Init Lightweight Chart
        const chart = LightweightCharts.createChart(chartContainer, {{
            layout: {{
                background: {{ color: '#131722' }},
                textColor: '#d1d4dc',
                fontSize: isMobile ? 11 : 12,
            }},
            grid: {{
                vertLines: {{ color: '#1e222d' }},
                horzLines: {{ color: '#1e222d' }},
            }},
            crosshair: {{
                mode: LightweightCharts.CrosshairMode.Normal,
            }},
            rightPriceScale: {{
                borderColor: '#2a2e39',
                autoScale: true,
                scaleMargins: {{
                    top: 0.1,
                    bottom: 0.22,
                }},
                entireTextOnly: false,
            }},
            timeScale: {{
                borderColor: '#2a2e39',
                timeVisible: true,
                secondsVisible: false,
                barSpacing: isMobile ? 13 : 18,
                minBarSpacing: 3,
                rightOffset: 3,
            }},
            handleScroll: true,
            handleScale: true,
        }});

        const candleSeries = chart.addCandlestickSeries({{
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderVisible: false,
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
            priceFormat: {{
                type: 'custom',
                formatter: (price) => {{
                    if (price <= 0) return '0';
                    if (price >= 100000000) {{
                        return (price / 100000000).toFixed(2) + ' 億';
                    }} else if (price >= 10000) {{
                        return (price / 10000).toFixed(0) + ' 萬';
                    }}
                    return price.toLocaleString();
                }}
            }},
            autoscaleInfoProvider: (original) => {{
                const res = original();
                if (res !== null && res.priceRange) {{
                    const minP = res.priceRange.minValue;
                    const maxP = res.priceRange.maxValue;
                    const diff = maxP - minP;
                    const pad = diff > 0 ? diff * 0.08 : (maxP > 0 ? maxP * 0.05 : 1000);
                    return {{
                        priceRange: {{
                            minValue: Math.max(1, minP - pad),
                            maxValue: maxP + pad,
                        }},
                    }};
                }}
                return res;
            }},
        }});

        const volumeSeries = chart.addHistogramSeries({{
            color: '#26a69a',
            priceFormat: {{ type: 'volume' }},
            priceScaleId: 'volume_scale',
        }});

        chart.priceScale('volume_scale').applyOptions({{
            scaleMargins: {{
                top: 0.82,
                bottom: 0,
            }},
            visible: false,
        }});

        // Responsive Resize Observer
        const resizeObserver = new ResizeObserver(entries => {{
            if (!entries || entries.length === 0) return;
            const {{ width, height }} = entries[0].contentRect;
            chart.applyOptions({{ width: Math.floor(width), height: Math.floor(height) }});
        }});
        resizeObserver.observe(chartContainer);

        function formatMeso(val) {{
            if (val === null || val === undefined || isNaN(val)) return '--';
            if (val >= 100000000) {{
                return (val / 100000000).toFixed(2) + ' 億';
            }} else if (val >= 10000) {{
                return (val / 10000).toFixed(0) + ' 萬';
            }}
            return val.toLocaleString();
        }}

        function updateChart() {{
            if (!currentItem || !allData[currentItem]) return;
            const itemObj = allData[currentItem];
            const candles = itemObj[currentTf] || [];
            const lowestAsk = itemObj.lowest_ask;

            // Format for TradingView (time is already pre-formatted in python)
            const cData = candles.map(c => ({{
                time: c.time,
                open: c.open,
                high: c.high,
                low: c.low,
                close: c.close,
            }}));

            const vData = candles.map(c => ({{
                time: c.time,
                value: c.volume,
                color: c.close >= c.open ? 'rgba(38, 166, 154, 0.45)' : 'rgba(239, 83, 80, 0.45)'
            }}));

            // Strictly ascending
            cData.sort((a, b) => (a.time > b.time ? 1 : (a.time < b.time ? -1 : 0)));
            vData.sort((a, b) => (a.time > b.time ? 1 : (a.time < b.time ? -1 : 0)));

            candleSeries.setData(cData);
            volumeSeries.setData(vData);

            // Auto-scale price axis tightly
            chart.priceScale('right').applyOptions({{
                autoScale: true,
            }});

            if (candles.length > 0) {{
                const latest = candles[candles.length - 1];
                valClose.textContent = formatMeso(latest.close);
                valClose.className = "metric-val " + (latest.close >= latest.open ? "c-up" : "c-down");
                valVwap.textContent = formatMeso(latest.vwap);
                valVol.textContent = latest.volume.toLocaleString() + " 張";

                // Max/Min in dataset
                const allHighs = candles.map(c => c.high);
                const allLows = candles.map(c => c.low);
                const maxH = Math.max(...allHighs);
                const minL = Math.min(...allLows);
                valRange.textContent = formatMeso(maxH) + " / " + formatMeso(minL);

                if (lowestAsk) {{
                    valAsk.textContent = formatMeso(lowestAsk);
                    const spread = ((lowestAsk - latest.close) / latest.close) * 100;
                    valSpread.textContent = (spread >= 0 ? "+" : "") + spread.toFixed(1) + "%";
                    valSpread.className = "metric-val " + (spread >= 0 ? "c-up" : "c-down");
                }} else {{
                    valAsk.textContent = "無掛賣";
                    valSpread.textContent = "N/A";
                    valSpread.className = "metric-val";
                }}
            }} else {{
                valClose.textContent = "無成交數據";
                valClose.className = "metric-val";
                valVwap.textContent = "--";
                valVol.textContent = "--";
                valRange.textContent = "--";
                valAsk.textContent = lowestAsk ? formatMeso(lowestAsk) : "--";
                valSpread.textContent = "--";
                valSpread.className = "metric-val";
            }}

            chart.timeScale().fitContent();
        }}

        // Dynamic Crosshair / Touch Legend Update
        chart.subscribeCrosshairMove((param) => {{
            if (!param || !param.time || !param.seriesData) return;
            const cItem = param.seriesData.get(candleSeries);
            const vItem = param.seriesData.get(volumeSeries);
            if (cItem) {{
                valClose.textContent = formatMeso(cItem.close);
                valClose.className = "metric-val " + (cItem.close >= cItem.open ? "c-up" : "c-down");
                valRange.textContent = formatMeso(cItem.high) + " / " + formatMeso(cItem.low);
            }}
            if (vItem) {{
                valVol.textContent = vItem.value.toLocaleString() + " 張";
            }}
        }});

        selector.addEventListener("change", (e) => {{
            currentItem = e.target.value;
            updateChart();
        }});

        document.querySelectorAll(".btn-tf").forEach(btn => {{
            btn.addEventListener("click", () => {{
                document.querySelectorAll(".btn-tf").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                currentTf = btn.getAttribute("data-tf");
                updateChart();
            }});
        }});

        // Initial render
        updateChart();
    </script>
</body>
</html>
"""
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    with open(DOCS_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Generated Phase 2 Candlestick Dashboard: {OUTPUT_HTML} and {DOCS_HTML}")
    return OUTPUT_HTML

if __name__ == "__main__":
    out = generate_dashboard_html()
