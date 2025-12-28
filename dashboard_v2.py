import streamlit as st
import pandas as pd
import sqlite3
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone
import ccxt
import json
import requests
import os
from streamlit_autorefresh import st_autorefresh
import streamlit.components.v1 as components

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="Institutional BTC Inflows", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS STYLING ---
st.markdown("""
<style>
    /* Clean up main container */
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    /* Hide Streamlit footer */
    footer {visibility: hidden;}
    /* Hide hamburger menu */
    #MainMenu {visibility: hidden;}
    
    /* Metrics Styling */
    [data-testid="stMetricValue"] {
        font-size: 2rem !important;
        font-weight: 700 !important;
        color: #FFFFFF !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 1rem !important;
        color: #A0A0A0 !important;
    }
</style>
""", unsafe_allow_html=True)

# Database setup
DB_FILE = "inflows.db"

# --- DATA LOADING & PROCESSING ---
@st.cache_data(ttl=60)
def load_and_process_data(start_dt, end_dt, resample_freq='1min'):
    conn = sqlite3.connect(DB_FILE)
    query = "SELECT * FROM inflows WHERE timestamp >= ? AND timestamp <= ?"
    
    s_str = str(start_dt)
    e_str = str(end_dt)
    
    df = pd.read_sql_query(query, conn, params=(s_str, e_str))
    conn.close()
    
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed', utc=True).dt.tz_localize(None)
    
    mask = (df['timestamp'] >= start_dt) & (df['timestamp'] <= end_dt)
    df = df.loc[mask].copy()

    # Determine Direction based on Raw Data Alert Name
    def get_flow_type(raw_json):
        try:
            data = json.loads(raw_json)
            name = data.get('alertName', '').lower()
            if "btc_inflow" in name: return "IN"
            if "btc_outflow" in name: return "OUT"
            return None # Filter out non-matching BTC alerts (e.g. Price Alerts)
        except: return None
        
    df['flow_type'] = df['raw_data'].apply(get_flow_type)
    df = df.dropna(subset=['flow_type']) # Keep only valid IN/OUT alerts

    # 1. RESAMPLE TO CANDLES (Pivot on flow_type)
    df_hourly = df.set_index('timestamp').groupby([pd.Grouper(freq=resample_freq), 'flow_type'])['amount_usd'].sum().unstack(fill_value=0)
    
    full_idx = pd.date_range(start=start_dt, end=end_dt, freq=resample_freq)
    df_hourly = df_hourly.reindex(full_idx, fill_value=0)
    df_hourly.index.name = 'timestamp'
    
    if 'IN' not in df_hourly.columns: df_hourly['IN'] = 0.0
    if 'OUT' not in df_hourly.columns: df_hourly['OUT'] = 0.0
    
    return df, df_hourly

@st.cache_data(ttl=300)
def fetch_btc_price_analysis(start_dt, end_dt, interval='1m'):
    try:
        exchange = ccxt.binance({'enableRateLimit': True})
        since = int((start_dt - timedelta(minutes=60)).timestamp() * 1000)
        end_ts = int(end_dt.timestamp() * 1000)
        
        all_ohlcv = []
        while True:
            ohlcv = exchange.fetch_ohlcv('BTC/USDT', interval, since=since, limit=1000)
            if not ohlcv: break
            
            all_ohlcv.extend(ohlcv)
            last_ts = ohlcv[-1][0]
            if last_ts >= end_ts or len(ohlcv) < 1000: break
            since = last_ts + 1
            
        if not all_ohlcv: return pd.DataFrame()
            
        columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        df = pd.DataFrame(all_ohlcv, columns=columns)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        mask = (df.index >= start_dt) & (df.index <= end_dt)
        return df.loc[mask]
    except Exception as e:
        print(f"Price Fetch Error: {e}")
        return pd.DataFrame()



def determine_signal_state(row):
    inflow = row.get('rolling_in', 0) or 0
    baseline = row.get('avg_baseline', 0) or 1
    outflow = row.get('green_outflow', 0) or 0
    if baseline < 1: baseline = 1
    
    in_ratio = inflow / baseline
    
    # Strong Sell Condition
    if in_ratio > 3.0:
        return "SELL"
    
    # Strong Buy Condition
    if outflow > inflow and outflow > (baseline * 1.5):
        return "BUY"
        
    return "NEUTRAL"

def render_sync_chart_js(price_df, inflow_df, rolling_window, baseline_window, trend_window, outflow_window, markers_json):
    if inflow_df.empty: return

    # 1. ALIGNMENT: Reindex Price to match Inflow (Master Time Range)
    combined_df = inflow_df.join(price_df, rsuffix='_p')
    
    price_data = []
    inflow_data = []
    avg_data = []
    trend_data = []    # White Line
    outflow_data = []  # Green Line
    price_line_data = [] 
    
    for ts, row in combined_df.iterrows():
        t_val = int(ts.replace(tzinfo=timezone.utc).timestamp())
        
        # --- PRICE DATA ---
        if pd.notna(row['close']):
            price_data.append({
                "time": t_val, "open": row['open'], "high": row['high'], "low": row['low'], "close": row['close']
            })
            price_line_data.append({"time": t_val, "value": row['close']})
        else:
            price_data.append({"time": t_val})
            price_line_data.append({"time": t_val})

        # --- FLOW DATA ---
        val = row.get('rolling_in', 0)
        avg = row.get('avg_baseline', 0)
        trend = row.get('white_trend', 0)
        out = row.get('green_outflow', 0)
        
        if pd.isna(val): val = 0
        if pd.isna(avg): avg = 0
        if pd.isna(trend): trend = 0
        if pd.isna(out): out = 0
            
        inflow_data.append({"time": t_val, "value": val})
        avg_data.append({"time": t_val, "value": avg})
        trend_data.append({"time": t_val, "value": trend})
        outflow_data.append({"time": t_val, "value": out})

    p_json = json.dumps(price_data)
    i_json = json.dumps(inflow_data)
    a_json = json.dumps(avg_data)
    t_json = json.dumps(trend_data)
    o_json = json.dumps(outflow_data)
    pl_json = json.dumps(price_line_data)
    
    chart_height = 1000 
    
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        body {{ margin: 0; padding: 0; background-color: #0E1117; color: white; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; overflow: hidden; }}
        .container {{ display: flex; flex-direction: column; gap: 2px; height: 100vh; }}
        #chart_price {{ flex: 1; width: 100%; position: relative; }}
        #chart_inflow {{ flex: 1; width: 100%; position: relative; }}
        .legend {{ position: absolute; z-index: 10; top: 12px; left: 12px; font-size: 13px; font-weight: 500; pointer-events: none; text-shadow: 1px 1px 2px rgba(0,0,0,0.5); }}
    </style>
    </head>
    <body>
    <div class="container">
        <div style="position: relative; height: 100%; flex: 1;">
            <div id="chart_price" style="height: 100%"></div>
            <div class="legend" style="color: #AC64FF">BTC/USDT Price</div>
        </div>
        <div style="position: relative; height: 100%; flex: 1;">
            <div id="chart_inflow" style="height: 100%"></div>
            <div class="legend" style="color: #EF553B">Inflow ({rolling_window}m) <span style="color: #3B82F6">| Avg ({baseline_window}m)</span> <span style="color: #FFFFFF">| Trend ({trend_window}m)</span> <span style="color: #10B981">| Outflow ({outflow_window}m)</span></div>
        </div>
    </div>
    <script>
        const pData = {p_json};
        const iData = {i_json};
        const aData = {a_json};
        const tData = {t_json};
        const oData = {o_json};
        const plData = {pl_json};
        const markersData = {markers_json};
        
        const chartP = LightweightCharts.createChart(document.getElementById('chart_price'), {{
            layout: {{ background: {{ color: '#0E1117' }}, textColor: '#9CA3AF' }},
            localization: {{ timezone: 'Etc/UTC' }},
            grid: {{ vertLines: {{ color: '#1F2937' }}, horzLines: {{ color: '#1F2937' }} }},
            timeScale: {{ timeVisible: true, secondsVisible: false, borderColor: '#374151', rightOffset: 15 }},
            rightPriceScale: {{ borderColor: '#374151' }},
            crosshair: {{ 
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {{ visible: false, labelVisible: false }},
                horzLine: {{ visible: false, labelVisible: false }}
            }},
        }});
        
        const candleSeries = chartP.addCandlestickSeries({{
            upColor: '#10B981', downColor: '#EF4444', borderVisible: false, wickUpColor: '#10B981', wickDownColor: '#EF4444',
            crosshairMarkerVisible: false,
            lastValueVisible: false, 
            priceLineVisible: false
        }});
        candleSeries.setData(pData);
        candleSeries.setMarkers(markersData);

        const chartI = LightweightCharts.createChart(document.getElementById('chart_inflow'), {{
            layout: {{ background: {{ color: '#0E1117' }}, textColor: '#9CA3AF' }},
            localization: {{ timezone: 'Etc/UTC' }},
            grid: {{ vertLines: {{ color: '#1F2937' }}, horzLines: {{ color: '#1F2937' }} }},
            timeScale: {{ timeVisible: true, secondsVisible: false, borderColor: '#374151', rightOffset: 15 }},
            rightPriceScale: {{ borderColor: '#374151' }},
            leftPriceScale: {{ visible: false, borderColor: '#374151' }},
            crosshair: {{ 
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {{ visible: false, labelVisible: false }},
                horzLine: {{ visible: false, labelVisible: false }}
            }},
        }});
        
        const priceOverlay = chartI.addLineSeries({{
            color: 'rgba(172, 100, 255, 0.8)',
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            priceScaleId: 'left',
            crosshairMarkerVisible: false,
            lastValueVisible: false, 
            priceLineVisible: false
        }});
        priceOverlay.setData(plData);

        // 1. Red Area (Inflow)
        const inflowSeries = chartI.addAreaSeries({{ 
            lineColor: '#EF553B', 
            topColor: 'rgba(239, 85, 59, 0.5)', 
            bottomColor: 'rgba(239, 85, 59, 0.0)', 
            lineWidth: 2, 
            priceScaleId: 'right',
            crosshairMarkerVisible: false,
            lastValueVisible: false, 
            priceLineVisible: false
        }});
        inflowSeries.setData(iData);
        
        // 2. Blue Line (Baseline)
        const avgSeries = chartI.addLineSeries({{ 
            color: '#3B82F6', 
            lineWidth: 2, 
            lineStyle: LightweightCharts.LineStyle.Solid, 
            priceScaleId: 'right',
            crosshairMarkerVisible: false,
            lastValueVisible: false, 
            priceLineVisible: false
        }});
        avgSeries.setData(aData);
        
        // 3. White Line (Trend)
        const trendSeries = chartI.addLineSeries({{ 
            color: '#FFFFFF', 
            lineWidth: 2, 
            lineStyle: LightweightCharts.LineStyle.Solid, 
            priceScaleId: 'right',
            crosshairMarkerVisible: false,
            lastValueVisible: false, 
            priceLineVisible: false
        }});
        trendSeries.setData(tData);

        // 4. Green Line (Outflow)
        const outflowSeries = chartI.addLineSeries({{ 
            color: '#10B981', 
            lineWidth: 2, 
            lineStyle: LightweightCharts.LineStyle.Solid, 
            priceScaleId: 'right',
            crosshairMarkerVisible: false,
            lastValueVisible: false, 
            priceLineVisible: false
        }});
        outflowSeries.setData(oData);

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
        chartP.timeScale().fitContent();
    </script>
    </body>
    </html>
    """
    components.html(html_code, height=chart_height, scrolling=False)


# --- UI SETUP ---
st.title("Institutional BTC Inflows")
st.caption("Real-time Exchange Inflow Monitoring & Price Correlation")

# --- SETTINGS PERSISTENCE ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "dashboard_settings.json")

def load_config():
    """Load settings from JSON file with error handling."""
    default_settings = {
        's_resolution': "1 Minute",
        's_inflow': 15,
        's_baseline': 60,
        's_trend': 30,
        's_outflow': 30
    }
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
                default_settings.update(saved)
    except Exception as e:
        print(f"Error loading settings: {e}")
    return default_settings

    return default_settings

def save_config_manual(res, inf, base, trd, out):
    """Manually Save values to JSON file."""
    settings = {
        's_resolution': res,
        's_inflow': inf,
        's_baseline': base,
        's_trend': trd,
        's_outflow': out
    }
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f)
        st.toast(f"Saved: {inf}m / {out}m 💾", icon="✅") 
    except Exception as e:
        st.error(f"Failed to save settings: {e}")

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/4/46/Bitcoin.svg", width=50)
    st.title("Institutional Inflow v2")
    
    # --- INITIALIZATION LOGIC ---
    if 'settings_initialized' not in st.session_state:
        config = load_config()
        st.session_state['s_resolution'] = config['s_resolution']
        st.session_state['s_inflow'] = int(config['s_inflow'])
        st.session_state['s_baseline'] = int(config['s_baseline'])
        st.session_state['s_trend'] = int(config['s_trend'])
        st.session_state['s_outflow'] = int(config['s_outflow'])
        st.session_state.settings_initialized = True
        
    # Placeholder for Live Metrics (To appear at top)
    st.markdown("### 🦅 AI Signal")
    signal_container = st.container()
    
    st.header("Control Panel")
    
    # 1. RESOLUTION
    # Initialize index based on saved string
    res_index = 0 if st.session_state['s_resolution'] == "1 Minute" else 1
    
    timeframe_label = st.selectbox(
        "Resolution", 
        ["1 Minute", "5 Minutes"], 
        index=res_index,
        key="w_resolution"
    )
    
    # Resolution Dependent Variables
    if timeframe_label == "1 Minute":
        resample_freq = "1min"; api_interval = "1m"; min_win = 1; step_win = 1
    else:
        resample_freq = "5min"; api_interval = "5m"; min_win = 5; step_win = 5

    # 2. STRATEGY PRESETS
    STRATEGY_PRESETS = {
        "Custom": {},
        "🏎️ Scalper (Fast)": {"in": 5, "base": 30, "trend": 15, "out": 15},
        "⚖️ Day Trader (Balanced)": {"in": 15, "base": 60, "trend": 30, "out": 30},
        "🐋 Swing Trader (Slow)": {"in": 30, "base": 120, "trend": 60, "out": 60}
    }
    
    def apply_strategy():
        sel = st.session_state.get('w_strategy')
        if sel and sel != "Custom":
            vals = STRATEGY_PRESETS[sel]
            st.session_state['s_inflow'] = vals['in']
            st.session_state['s_baseline'] = vals['base']
            st.session_state['s_trend'] = vals['trend']
            st.session_state['s_outflow'] = vals['out']
            # Note: We don't auto-save here, we let the form pre-fill so user can review and Click Save.
            # OR we could save immediately. Given the request "automatically configure", pre-filling is safest.
            # The 'value' params in number_input below will pick up these new session state values on rerun.

    st.selectbox(
        "Strategy Preset", 
        options=list(STRATEGY_PRESETS.keys()),
        index=0,
        key="w_strategy",
        on_change=apply_strategy,
        help="Select a pre-configured strategy to auto-fill the settings below."
    )

    # 3. NUMERIC INPUTS (Form)
    with st.expander("⚙️ Advanced Settings", expanded=True):
        with st.form("settings_form"):
            st.caption("Adjust Rolling Windows (Minutes)")
            
            # Retrieve Source of Truth (Updated by Preset or Loaded)
            val_in = max(min_win, st.session_state['s_inflow'])
            val_base = max(min_win, st.session_state['s_baseline'])
            val_trend = max(5, st.session_state['s_trend'])
            val_out = max(5, st.session_state['s_outflow'])
            
            # Input Boxes with Tooltips
            new_inflow = st.number_input(
                "🟠 Inflow Smoothing", 
                min_value=min_win, max_value=240, value=val_in, step=step_win,
                help="How smooth the Red Area looks. Higher number = smoother but slower."
            )
            new_baseline = st.number_input(
                "🔵 Baseline Window", 
                min_value=min_win, max_value=480, value=val_base, step=step_win,
                help="The Blue Line average. Compares today vs the last X minutes."
            )
            new_trend = st.number_input(
                "⚪ Trend Window", 
                min_value=5, max_value=480, value=val_trend, step=step_win,
                help="The White Line direction. Shows if selling is speeding up or slowing down."
            )
            new_outflow = st.number_input(
                "🟢 Outflow Window", 
                min_value=5, max_value=480, value=val_out, step=step_win,
                help="The Green Line. Shows how much BTC is leaving exchanges (Bullish)."
            )
            
            # Submit Button
            submitted = st.form_submit_button("💾 Save Configuration")
            
            if submitted:
                # Update Session State Source of Truth
                st.session_state['s_resolution'] = timeframe_label
                st.session_state['s_inflow'] = new_inflow
                st.session_state['s_baseline'] = new_baseline
                st.session_state['s_trend'] = new_trend
                st.session_state['s_outflow'] = new_outflow
                
                # Save to Disk with EXPLICIT values
                save_config_manual(timeframe_label, new_inflow, new_baseline, new_trend, new_outflow)
                
                # Rerun to apply changes immediately
                st.rerun()
        
        # EXPOSE VARIABLES FOR DOWNSTREAM LOGIC
        inflow_rolling_window = st.session_state['s_inflow']
        baseline_window = st.session_state['s_baseline']
        trend_window = st.session_state['s_trend']
        outflow_window = st.session_state['s_outflow']
        
        # Date & Refresh (Outside form)
        date_range = st.date_input("Date Range", [datetime.now() - timedelta(days=1), datetime.now()])
        refresh_enabled = st.checkbox("Auto-Refresh (5s)", value=False)

    if refresh_enabled:
        count = st_autorefresh(interval=5000, key="datarefresh") # 5s refresh

    st.markdown("---")
    
    # Statistics Expander
    with st.expander("📊 Database Statistics", expanded=True):
        try:
            conn = sqlite3.connect(DB_FILE)
            total_count = pd.read_sql_query("SELECT COUNT(*) as c FROM inflows", conn).iloc[0]['c']
            skipped_count = pd.read_sql_query("SELECT COUNT(*) as c FROM skipped_inflows", conn).iloc[0]['c']
            in_count = pd.read_sql_query("SELECT COUNT(*) as c FROM inflows WHERE raw_data LIKE '%btc_inflow%'", conn).iloc[0]['c']
            out_count = pd.read_sql_query("SELECT COUNT(*) as c FROM inflows WHERE raw_data LIKE '%btc_outflow%'", conn).iloc[0]['c']
            conn.close()
            
            st.write(f"**Total Events**: {total_count}")
            c_stat1, c_stat2 = st.columns(2)
            c_stat1.metric("🔴 Inflows", in_count)
            c_stat2.metric("🟢 Outflows", out_count)
            st.caption(f"⚠️ Skipped: {skipped_count}")
        except Exception as e:
            st.error(f"Stats Error: {e}")

    # Connection Status Expander
    with st.expander("🔌 Connection Status", expanded=False):
        # Webhook
        def get_ngrok_url():
            try:
                response = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=1)
                tunnels = response.json().get('tunnels', [])
                for t in tunnels:
                    if t.get('proto') == 'https': return t.get('public_url')
            except: pass
            return None
            
        current_url = get_ngrok_url()
        if current_url:
            st.success(f"Webhook Active", icon="🟢")
            st.code(f"{current_url}/webhook", language="text")
        else:
            st.warning("Webhook Disconnected", icon="🔴")
            
        # Local Server
        try:
            if requests.get("http://localhost:8000/", timeout=1).status_code == 200:
                st.info("Backend: Online")
        except: st.error("Backend: Offline")


# --- MAIN CONTENT ---

# Date Logic
if len(date_range) == 2:
    start_date, end_date = date_range
    start_dt = datetime.combine(start_date, datetime.min.time())
    current_utc = datetime.now(timezone.utc).replace(tzinfo=None) # Keep naive for compatibility with other logic if needed, or better yet, make everything aware.
    # The code later compares date() and uses naive datetimes mostly. 
    # load_and_process_data uses 'mixed' and then ignores timezone (lines 57). 
    # So I should probably keep it naive or ensure compatibility.
    # The warning suggests `datetime.now(datetime.UTC)`. 
    # Let's use datetime.now(timezone.utc) and strip tz if the rest of the app expects naive.
    # Looking at line 57: df['timestamp'] = ... .dt.tz_localize(None).
    # So the app works with NAIVE UTC.
    
    current_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # Smart Clipping for "Today"
    if end_date >= current_utc.date(): end_dt = current_utc
    else: end_dt = datetime.combine(end_date, datetime.max.time())
    
    # Fetch Data
    raw_df, hourly_df = load_and_process_data(start_dt, end_dt, resample_freq=resample_freq)

    # Process Metrics
    if hourly_df.empty: hourly_df = pd.DataFrame(columns=['IN', 'OUT']) 
    chart_df = hourly_df.copy().sort_index()
    
    # Inflow Calc (Red Area - INFLOW ONLY)
    chart_df['rolling_in'] = chart_df['IN'].rolling(f'{inflow_rolling_window}min').sum()
    
    # Trend Calc (White Line - INFLOW TREND)
    chart_df['white_trend'] = chart_df['IN'].rolling(f'{trend_window}min').sum()
    
    # Outflow Calc (Green Line - OUTFLOW)
    chart_df['green_outflow'] = chart_df['OUT'].rolling(f'{outflow_window}min').sum()
    
    # Baseline Calc (Blue Line - INFLOW BASELINE)
    freq_int = 1 if resample_freq == "1min" else 5
    shift_periods = int(10 / freq_int)
    chart_df['shifted'] = chart_df['rolling_in'].shift(shift_periods)
    chart_df['avg_baseline'] = chart_df['shifted'].rolling(f'{baseline_window}min').mean()
    
    # Chart Markers Logic
    markers = []
    prev_state = "NEUTRAL"
    
    for ts, row in chart_df.iterrows():
        curr_state = determine_signal_state(row)
        
        if curr_state != prev_state and curr_state != "NEUTRAL":
            t_val = int(ts.replace(tzinfo=timezone.utc).timestamp())
            
            if curr_state == "SELL":
                markers.append({
                    "time": t_val, "position": "aboveBar", "color": "#EF4444", "shape": "arrowDown", "text": "SHORT"
                })
            elif curr_state == "BUY":
                 markers.append({
                    "time": t_val, "position": "belowBar", "color": "#10B981", "shape": "arrowUp", "text": "LONG"
                })
        
        prev_state = curr_state
        
    markers_json = json.dumps(markers)

    # Chart (Moved to Top)
    st.markdown("### Price vs Inflow Analysis")
    price_df = fetch_btc_price_analysis(start_dt, end_dt, interval=api_interval)
    render_sync_chart_js(price_df, chart_df, inflow_rolling_window, baseline_window, trend_window, outflow_window, markers_json)
    
    st.markdown("---")

    # Top Metrics (Moved Below Chart)
    total_in = chart_df['IN'].sum()
    total_out = chart_df['OUT'].sum()
    net_flow = total_in - total_out
    
    # AI Signal Widget (Using Helper)
    def get_market_signal_text(df):
        if df.empty: return "NO DATA", "#888888", "Waiting for data..."
        state = determine_signal_state(df.iloc[-1])
        
        if state == "SELL":
            # Strong Sell -> RED
            return "STRONG SELL", "#EF4444", "High Inflow vs Baseline! Heavy dumping expected."
        elif state == "BUY":
            # Strong Buy -> GREEN
            return "STRONG BUY", "#10B981", "Outflow Dominance! Whales withdrawing."
        # Neutral -> WHITE
        return "NEUTRAL", "#FFFFFF", "Flows are balanced."

    sig_label, sig_color, sig_desc = get_market_signal_text(chart_df)
    
    # Populate Sidebar Metrics
    with signal_container:
        # Custom HTML for colorized Signal
        st.markdown(f"""
            <div style="
                background-color: #262730; 
                padding: 10px; 
                border-radius: 8px; 
                border-left: 5px solid {sig_color};
                margin-bottom: 15px;
            ">
                <h3 style="margin: 0; color: {sig_color}; font-size: 24px;">{sig_label}</h3>
                <p style="margin: 5px 0 0 0; color: #CCCCCC; font-size: 14px;">{sig_desc}</p>
            </div>
        """, unsafe_allow_html=True)
        
        c_s1, c_s2 = st.columns(2)
        c_s1.metric("Net Flow", f"${net_flow:,.0f}", delta=f"${total_in:,.0f} In")
        c_s2.metric("Outflow", f"${total_out:,.0f}", delta="Total Out")
    
    # --- LIVE DATA FEED (Fragment) ---
    @st.fragment
    def render_feed_section():
        st.markdown("---")
        c_feed, c_skipped = st.columns([3, 1])
        
        with c_feed:
            st.subheader("Live Inflow Feed")
            try:
                 conn = sqlite3.connect(DB_FILE)
                 logs_df = pd.read_sql_query("SELECT timestamp, amount_usd, destination, raw_data FROM inflows WHERE currency='BTC' ORDER BY timestamp DESC LIMIT 50", conn)
                 conn.close()
                 
                 if not logs_df.empty:
                     logs_df['timestamp'] = pd.to_datetime(logs_df['timestamp'])
                     # We need to ensure we compare apples to apples. if logs_df is naive (it is from sqlite), we need naive now.
                     now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                     
                     def format_time_ago(ts):
                         if ts.tzinfo: ts = ts.tz_convert(None)
                         diff = now_utc - ts
                         total_seconds = int(diff.total_seconds())
                         if total_seconds < 60: return f"{total_seconds}s ago"
                         if total_seconds < 3600: return f"{total_seconds // 60}m ago"
                         return ts.strftime('%H:%M')
                     
                     def get_sender(raw_json):
                         try:
                             data = json.loads(raw_json)
                             sender = data.get('fromAddressLabel')
                             if not sender: sender = data.get('fromAddress', {}).get('arkhamLabel', {}).get('name')
                             if not sender: sender = data.get('fromAddress', {}).get('address')
                             return sender if sender else "Unknown"
                         except: return "Unknown"

                     def get_alert_name(raw_json):
                         try:
                             data = json.loads(raw_json)
                             return data.get('alertName', 'Unknown')
                         except: return "Unknown"

                     display_df = pd.DataFrame()
                     display_df['Time'] = logs_df['timestamp'].apply(format_time_ago)
                     display_df['Alert'] = logs_df['raw_data'].apply(get_alert_name)
                     display_df['Amount'] = logs_df['amount_usd'].apply(lambda x: f"${x:,.0f}")
                     display_df['From'] = logs_df['raw_data'].apply(get_sender)
                     display_df['To'] = logs_df['destination']
                     
                     event = st.dataframe(
                         display_df, 
                         use_container_width=True, 
                         hide_index=True,
                         height=400,
                         on_select="rerun",
                         selection_mode="single-row"
                     )
                     
                     if len(event.selection['rows']) > 0:
                         selected_idx = event.selection['rows'][0]
                         raw_payload = logs_df.iloc[selected_idx]['raw_data']
                         st.markdown("#### 🔍 Selected Alert Details")
                         try:
                             st.json(json.loads(raw_payload))
                         except:
                             st.code(raw_payload)
                 else:
                     st.info("No recent inflows detected.")
            except Exception as e:
                st.error(f"Feed Error: {e}")

        with c_skipped:
             with st.expander("⚠️ Skipped Alerts", expanded=False):
                try:
                    conn = sqlite3.connect(DB_FILE)
                    skipped_df = pd.read_sql_query("SELECT timestamp, reason FROM skipped_inflows ORDER BY timestamp DESC LIMIT 20", conn)
                    conn.close()
                    if not skipped_df.empty:
                        st.dataframe(skipped_df, hide_index=True)
                    else:
                        st.caption("No skipped alerts.")
                except: pass

    render_feed_section()
else:
    st.info("Please select a date range.")
