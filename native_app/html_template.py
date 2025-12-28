
# native_app/html_template.py

def get_chart_html(rolling_window):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
    <script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        body {{ margin: 0; padding: 0; background-color: #131722; color: white; font-family: sans-serif; overflow: hidden; }}
        .container {{ display: flex; flex-direction: column; gap: 4px; height: 100vh; }}
        #chart_price {{ flex: 1; width: 100%; position: relative; }}
        #chart_inflow {{ flex: 1; width: 100%; position: relative; }}
        .legend {{ position: absolute; z-index: 10; top: 12px; left: 12px; font-size: 14px; pointer-events: none; text-shadow: 1px 1px 2px black; }}
        #error_log {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: red; font-size: 16px; background: rgba(0,0,0,0.8); padding: 20px; display: none; z-index: 1000; }}
    </style>
    </head>
    <body>
    <div id="error_log"></div>
    <div class="container">
        <div style="position: relative; height: 100%; flex: 1;">
            <div id="chart_price" style="height: 100%"></div>
            <div class="legend" style="color: #AC64FF">BTC Price (USDT)</div>
        </div>
        <div style="position: relative; height: 100%; flex: 1;">
            <div id="chart_inflow" style="height: 100%"></div>
            <div class="legend" style="color: #EF553B">Net Inflow ({rolling_window}m) vs 1h Lagged</div>
        </div>
    </div>

    <script>
        // Global chart instances
        let chartP, chartI;
        let candleSeries, inflowSeries, laggedSeries;

        window.onerror = function(msg, url, lineNo, columnNo, error) {{
            const div = document.getElementById('error_log');
            div.style.display = 'block';
            div.innerHTML = `<h3>JS Error</h3><p>${{msg}}</p><p>Line: ${{lineNo}}</p>`;
            return false;
        }};

        function initCharts() {{
            try {{
                // --- CHART 1: PRICE ---
                chartP = LightweightCharts.createChart(document.getElementById('chart_price'), {{
                    layout: {{ background: {{ color: '#131722' }}, textColor: '#D9D9D9' }},
                    grid: {{ vertLines: {{ color: '#2B2B43' }}, horzLines: {{ color: '#2B2B43' }} }},
                    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
                    timeScale: {{ timeVisible: true, secondsVisible: false }},
                }});
                
                candleSeries = chartP.addCandlestickSeries({{
                    upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350'
                }});

                // --- CHART 2: INFLOW ---
                chartI = LightweightCharts.createChart(document.getElementById('chart_inflow'), {{
                    layout: {{ background: {{ color: '#131722' }}, textColor: '#D9D9D9' }},
                    grid: {{ vertLines: {{ color: '#2B2B43' }}, horzLines: {{ color: '#2B2B43' }} }},
                    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
                    timeScale: {{ timeVisible: true, secondsVisible: false }},
                }});

                // Inflow Line (Red/Orange)
                inflowSeries = chartI.addLineSeries({{
                    color: '#EF553B', lineWidth: 2,
                    priceScaleId: 'right'
                }});
                
                // Lagged Line (Yellow Dotted)
                laggedSeries = chartI.addLineSeries({{
                    color: '#FFEB3B', lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Dotted,
                    priceScaleId: 'right'
                }});

                // --- SYNC LOGIC ---
                function syncCharts(c1, c2) {{
                    let isSyncing = false;
                    
                    c1.timeScale().subscribeVisibleLogicalRangeChange(range => {{
                        if (isSyncing) return;
                        isSyncing = true;
                        c2.timeScale().setVisibleLogicalRange(range);
                        isSyncing = false;
                    }});
                    
                    c2.timeScale().subscribeVisibleLogicalRangeChange(range => {{
                        if (isSyncing) return;
                        isSyncing = true;
                        c1.timeScale().setVisibleLogicalRange(range);
                        isSyncing = false;
                    }});
                }}
                
                syncCharts(chartP, chartI);
                
                // Initial resize
                new ResizeObserver(entries => {{
                    if (chartP) chartP.timeScale().fitContent();
                }}).observe(document.body);

            }} catch (err) {{
                document.getElementById('error_log').style.display = 'block';
                document.getElementById('error_log').innerHTML = `<h3>Init Error</h3><p>${{err.message}}</p>`;
            }}
        }}

        // Function called from Python to update data
        function updateData(pData, iData, lData) {{
            try {{
                if (pData && pData.length > 0) candleSeries.setData(pData);
                if (iData && iData.length > 0) inflowSeries.setData(iData);
                if (lData && lData.length > 0) laggedSeries.setData(lData);
            }} catch(e) {{
                console.error(e);
            }}
        }}

        initCharts();
    </script>
    </body>
    </html>
    """
