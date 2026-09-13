import sqlite3
import json
import webbrowser
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
                        t_val = int(datetime.strptime(raw_t, "%Y-%m-%d %H:%M:%S").timestamp())
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Artale 自由市場 K線分析儀 (Phase 2)</title>
    <script>{js_code}</script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }}
        body {{ background-color: #131722; color: #d1d4dc; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }}
        
        header {{
            background-color: #1e222d;
            padding: 12px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid #2a2e39;
        }}
        .logo {{ font-size: 1.25rem; font-weight: 700; color: #2962ff; display: flex; align-items: center; gap: 8px; }}
        .controls {{ display: flex; align-items: center; gap: 16px; }}
        select, button {{
            background-color: #2a2e39;
            color: #d1d4dc;
            border: 1px solid #363c4e;
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 0.9rem;
            cursor: pointer;
            outline: none;
        }}
        select:focus, button:hover {{ border-color: #2962ff; }}
        .btn-tf.active {{ background-color: #2962ff; color: #fff; font-weight: 600; }}

        .metric-bar {{
            background-color: #181c27;
            padding: 10px 24px;
            display: flex;
            gap: 32px;
            border-bottom: 1px solid #2a2e39;
            font-size: 0.9rem;
        }}
        .metric {{ display: flex; flex-direction: column; gap: 2px; }}
        .metric-label {{ color: #787b86; font-size: 0.75rem; text-transform: uppercase; }}
        .metric-val {{ font-weight: 700; font-size: 1.05rem; }}
        .c-up {{ color: #26a69a; }}
        .c-down {{ color: #ef5350; }}
        .c-ask {{ color: #ff9800; }}

        #chart-container {{
            flex: 1;
            position: relative;
            width: 100%;
        }}
    </style>
</head>
<body>
    <header>
        <div class="logo">
            <span>🍁</span> Artale Market Candlestick Terminal (Phase 2)
        </div>
        <div class="controls">
            <select id="item-selector"></select>
            <div id="tf-buttons">
                <button class="btn-tf active" data-tf="1h">1小時 (1H)</button>
                <button class="btn-tf" data-tf="4h">4小時 (4H)</button>
                <button class="btn-tf" data-tf="1d">日線 (1D)</button>
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
            <span class="metric-label">買賣價差 (Ask Spread)</span>
            <span class="metric-val" id="val-spread">--</span>
        </div>
        <div class="metric">
            <span class="metric-label">成交均價 (VWAP)</span>
            <span class="metric-val" id="val-vwap">--</span>
        </div>
        <div class="metric">
            <span class="metric-label">成交總量 (Volume)</span>
            <span class="metric-val" id="val-vol">--</span>
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

        // Populate item selector
        items.forEach(it => {{
            const opt = document.createElement("option");
            opt.value = it;
            opt.textContent = it;
            selector.appendChild(opt);
        }});

        // Init Lightweight Chart
        const chart = LightweightCharts.createChart(chartContainer, {{
            layout: {{
                background: {{ color: '#131722' }},
                textColor: '#d1d4dc',
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
                    bottom: 0.25,
                }},
            }},
            timeScale: {{
                borderColor: '#2a2e39',
                timeVisible: true,
                secondsVisible: false,
                barSpacing: 18,
                minBarSpacing: 4,
                rightOffset: 5,
            }},
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
                    const pad = diff > 0 ? diff * 0.1 : (maxP > 0 ? maxP * 0.05 : 1000);
                    return {{
                        priceRange: {{
                            minValue: Math.max(0, minP - pad),
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
                top: 0.8,
                bottom: 0,
            }},
        }});

        window.addEventListener('resize', () => {{
            chart.applyOptions({{
                width: chartContainer.clientWidth,
                height: chartContainer.clientHeight
            }});
        }});
        chart.applyOptions({{
            width: chartContainer.clientWidth,
            height: chartContainer.clientHeight
        }});

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
                color: c.close >= c.open ? 'rgba(38, 166, 154, 0.5)' : 'rgba(239, 83, 80, 0.5)'
            }}));

            // Strictly ascending
            cData.sort((a, b) => (a.time > b.time ? 1 : (a.time < b.time ? -1 : 0)));
            vData.sort((a, b) => (a.time > b.time ? 1 : (a.time < b.time ? -1 : 0)));

            candleSeries.setData(cData);
            volumeSeries.setData(vData);

            // Force price scale and volume scale to auto-zoom to the selected item
            chart.priceScale('right').applyOptions({{
                autoScale: true,
            }});
            chart.priceScale('volume_scale').applyOptions({{
                autoScale: true,
            }});

            if (candles.length > 0) {{
                const latest = candles[candles.length - 1];
                valClose.textContent = latest.close.toLocaleString() + " 楓幣";
                valClose.className = "metric-val " + (latest.close >= latest.open ? "c-up" : "c-down");
                valVwap.textContent = latest.vwap.toLocaleString() + " 楓幣";
                valVol.textContent = latest.volume.toLocaleString() + " 張";

                if (lowestAsk) {{
                    valAsk.textContent = lowestAsk.toLocaleString() + " 楓幣";
                    const spread = ((lowestAsk - latest.close) / latest.close) * 100;
                    valSpread.textContent = (spread >= 0 ? "+" : "") + spread.toFixed(1) + "%";
                    valSpread.className = "metric-val " + (spread >= 0 ? "c-up" : "c-down");
                }} else {{
                    valAsk.textContent = "無現有掛賣";
                    valSpread.textContent = "N/A";
                }}
            }} else {{
                valClose.textContent = "無成交數據";
                valVwap.textContent = "--";
                valVol.textContent = "--";
                valAsk.textContent = lowestAsk ? lowestAsk.toLocaleString() + " 楓幣" : "--";
                valSpread.textContent = "--";
            }}

            chart.timeScale().fitContent();
        }}

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
