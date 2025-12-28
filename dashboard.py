import streamlit as st
import pandas as pd
import sqlite3
import plotly.graph_objects as go
from datetime import datetime, timedelta
import ccxt
from plotly.subplots import make_subplots
import numpy as np
import json
import requests
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Crypto Inflow Dashboard", layout="wide")

# --- CLIPBOARD/SECURE CONTEXT CHECK ---
# Browsers block clipboard access on insecure origins (like http://0.0.0.0).
# We inject JS to check this and warn the user.
st.markdown(
    """
    <script>
    if (!window.isSecureContext && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
        const warning = document.createElement('div');
        warning.style.padding = '1rem';
        warning.style.backgroundColor = '#FF4B4B';
        warning.style.color = 'white';
        warning.style.textAlign = 'center';
        warning.style.fontWeight = 'bold';
        warning.style.position = 'fixed';
        warning.style.top = '0';
        warning.style.left = '0';
        warning.style.width = '100%';
        warning.style.zIndex = '999999';
        warning.innerHTML = '⚠️ Clipboard/Screenshots Disabled! You are accessing via an insecure origin (' + window.location.hostname + ').<br>Please use <b><a href="http://localhost:8501" style="color: yellow;">http://localhost:8501</a></b> to enable clipboard features.';
        document.body.prepend(warning);
    }
    </script>
    """,
    unsafe_allow_html=True
)

# Database setup
DB_FILE = "inflows.db"

# --- DATA LOADING & PROCESSING ---
@st.cache_data(ttl=60)
def load_and_process_data(start_dt, end_dt, resample_freq='1min'):
    conn = sqlite3.connect(DB_FILE)
    
    # optimize: filter by date in SQL
    query = "SELECT * FROM inflows WHERE timestamp >= ? AND timestamp <= ?"
    
    # Ensure params are strings matches DB format (simple ISO mostly works)
    # The DB has +00:00, so we should ideally match that, but lexicographical generic comparison works
    # if we are consistent.
    s_str = str(start_dt)
    e_str = str(end_dt)
    
    df = pd.read_sql_query(query, conn, params=(s_str, e_str))
    conn.close()
    
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
        
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed', utc=True).dt.tz_localize(None)
    
    # Extra safety filter if SQL didn't catch edge cases perfectly
    mask = (df['timestamp'] >= start_dt) & (df['timestamp'] <= end_dt)
    df = df.loc[mask].copy()
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    # 1. RESAMPLE TO CANDLES
    df_hourly = df.set_index('timestamp').groupby([pd.Grouper(freq=resample_freq), 'currency'])['amount_usd'].sum().unstack(fill_value=0)
    
    if 'BTC' not in df_hourly.columns: df_hourly['BTC'] = 0.0
    # 2. CALCULATE NET FLOW DELTA (Just BTC Volume for now, or maintain structure)
    df_hourly['total_volume'] = df_hourly['BTC']
    return df, df_hourly

@st.cache_data(ttl=600)
def fetch_btc_price_analysis(start_dt, end_dt, interval='1m'):
    try:
        exchange = ccxt.binance({'enableRateLimit': True})
        since = int(start_dt.timestamp() * 1000)
        step_ms = 60000 if interval == '1m' else 300000
        
        all_ohlcv = []
        current_since = since
        
        while True:
            ohlcv = exchange.fetch_ohlcv('BTC/USDT', interval, since=current_since, limit=1000)
            if not ohlcv:
                break
            
            all_ohlcv.extend(ohlcv)
            
            last_timestamp = ohlcv[-1][0]
            if last_timestamp >= int(end_dt.timestamp() * 1000) or len(ohlcv) < 1000:
                break
                
            current_since = last_timestamp + step_ms
            
        if not all_ohlcv:
            return pd.DataFrame()
        columns = ['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']
        price_df = pd.DataFrame(all_ohlcv, columns=columns)
        
        price_df['timestamp'] = pd.to_datetime(price_df['timestamp'], unit='ms')
        price_df.set_index('timestamp', inplace=True)
        
        price_df = price_df[price_df.index <= end_dt]
        if price_df.empty:
            return pd.DataFrame()
        price_df['pct_change'] = price_df['Close'].pct_change() * 100
        return price_df
        
    except Exception as e:
        print(f"Error fetching data from Binance: {e}")
        return pd.DataFrame()

def run_backtest_simulation(df, avg_col='avg_30m', strategy_type='crossover', std_dev_mult=2.0):
    """
    Vectorized Strategy Simulation (100x Faster)
    """
    required_cols = ['rolling_btc', avg_col, 'Close']
    valid_df = df.dropna(subset=required_cols).copy()
    if valid_df.empty:
        return pd.DataFrame()

    # --- 1. PRE-CALCULATE INDICATORS (Vectorized) ---
    inflow = valid_df['rolling_btc']
    avg = valid_df[avg_col]
    
    # Inference for StdDev window if generic (fallback)
    # (Same heuristics as before but cleaner)
    window_for_std = 20
    try:
        if 'avg_' in avg_col:
            p_str = avg_col.split('avg_')[1].split('m')[0]
            val = int(p_str)
            # approximate simple row count from 5m data
            window_for_std = max(2, int(val / 5)) 
    except:
        pass

    if strategy_type == 'spike':
        std_dev = inflow.rolling(window=window_for_std).std()
        upper_band = avg + (std_dev * std_dev_mult)
        
        # Vectorized Conditions
        # SHORT: Inflow > Upper Band
        # LONG: Inflow < Average
        cond_short = (inflow > upper_band)
        cond_long = (inflow < avg)
    else: # Crossover
        cond_short = (inflow > avg)
        cond_long = (inflow < avg)
        
    # --- 2. VECTORIZED SIGNAL GENERATION ---
    # 1 = Long, -1 = Short, 0 = Neutral/Hold
    valid_df['raw_signal'] = np.select(
        [cond_short, cond_long], 
        [-1, 1], 
        default=0
    )
    
    # Fill 'Hold' (0) with previous signal to create continuous state
    valid_df['position'] = valid_df['raw_signal'].replace(0, np.nan).ffill()
    
    # --- 3. IDENTIFY TRADE EVENTS (Sparse Iteration) ---
    # We only care when position CHANGES
    valid_df['prev_pos'] = valid_df['position'].shift(1)
    
    # Filter for change events (Entry or Flip)
    # Valid change: current != prev AND current is not NaN
    change_mask = (valid_df['position'] != valid_df['prev_pos']) & (valid_df['position'].notna())
    
    # We always need a start. If first row has position, it's an entry.
    # The mask handles the first row if prev_pos is NaN? 
    # shift(1) puts NaN at 0. If pos[0] is 1, 1 != NaN -> True. So yes.
    
    event_df = valid_df[change_mask].copy()
    
    trades = []
    
    # Track open position
    # We iterate ONLY the events (much fewer rows)
    current_pos = None # 'LONG' or 'SHORT'
    entry_price = 0.0
    entry_time = None
    
    for time, row in event_df.iterrows():
        new_pos_code = row['position'] # 1 or -1
        new_pos = 'LONG' if new_pos_code == 1 else 'SHORT'
        price = row['Close']
        
        # If we have an open position, close it
        if current_pos is not None:
            # Cal PnL
            exit_price = price
            pnl = 0.0
            if current_pos == 'LONG':
                pnl = (exit_price - entry_price) / entry_price
            else:
                pnl = (entry_price - exit_price) / entry_price
                
            trades.append({
                'Entry Time': entry_time,
                'Type': current_pos,
                'Entry Price': entry_price,
                'Exit Time': time,
                'Exit Price': exit_price,
                'PnL %': pnl * 100,
                'Result': 'WIN' if pnl > 0 else 'LOSS'
            })
            
        # Open new position
        current_pos = new_pos
        entry_price = price
        entry_time = time
            
    return pd.DataFrame(trades)

@st.cache_data(ttl=60)
def optimize_strategy(df, periods, strategy_type='crossover', std_dev_mult=2.0):
    """
    Tests multiple rolling average periods and returns the best one based on Total Return.
    """
    results = []
    
    # Determine interval for window calculation
    try:
        diff = df.index.to_series().diff().median()
        interval_minutes = diff.total_seconds() / 60
        if interval_minutes == 0 or pd.isna(interval_minutes): interval_minutes = 1
    except:
        interval_minutes = 1
    
    for period in periods:
        col_name = f'avg_{period}m'
        w_size = max(1, int(period / interval_minutes))
        
        # Calculate MA
        df[col_name] = df['rolling_btc'].rolling(window=w_size, min_periods=1).mean()
        
        trades = run_backtest_simulation(df, avg_col=col_name, strategy_type=strategy_type, std_dev_mult=std_dev_mult)
        
        total_return = trades['PnL %'].sum() if not trades.empty else 0.0
        win_count = len(trades[trades['Result'] == 'WIN']) if not trades.empty else 0
        total_trades = len(trades)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0.0
        
        results.append({
            'Period (min)': period,
            'Total Return': total_return,
            'Win Rate': win_rate,
            'Trades': total_trades,
            'Avg PnL': trades['PnL %'].mean() if not trades.empty else 0.0
        })
        
        # Cleanup
        df.drop(columns=[col_name], inplace=True)
        
    results_df = pd.DataFrame(results)
    return results_df.sort_values(by='Total Return', ascending=False)

# --- UI SETUP ---
def get_ngrok_url():
    try:
        response = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=1)
        if response.status_code == 200:
            data = response.json()
            tunnels = data.get('tunnels', [])
            if tunnels:
                for tunnel in tunnels:
                    if tunnel.get('proto') == 'https':
                        return tunnel.get('public_url')
    except Exception:
        pass
    return None

st.title(f"BTC Inflow vs Price Action")
# Initialize Webhook URL (Internal)
current_url = get_ngrok_url()  
if not current_url: current_url = None
st.markdown("""
> **Hypothesis**: Significant BTC inflows to exchanges indicate potential selling pressure (Bearish).
""")
st.sidebar.header("Chart Settings")
with st.sidebar.expander("👁️ Chart Visibility", expanded=True):
    show_inflow = st.checkbox("Show Inflow Volume", value=True)
    show_avg = st.checkbox("Show Average Line", value=True)
    show_spike = st.checkbox("Show Spike Threshold", value=True)
    show_price = st.checkbox("Show BTC Price", value=True)
    show_trades = st.checkbox("Show Trade Markers", value=True)

st.sidebar.markdown("---")
# Cleaned up duplicate headers and empty logic blocks


st.sidebar.markdown("---")

# Validating Webhook URL (moved to bottom, logic kept)
# We will render this at the end of the script in the sidebar


timeframe_label = st.sidebar.selectbox("Timeframe", ["1 Minute", "5 Minutes"], index=1)
if timeframe_label == "1 Minute":
    resample_freq = "1min"; api_interval = "1m"; tf_short = "1m"
else:
    resample_freq = "5min"; api_interval = "5m"; tf_short = "5m"

# Inflow Rolling Window Control
inflow_rolling_window = st.sidebar.slider("Inflow Rolling Window (m)", 1, 60, 5, help="Sum BTC inflow over this many minutes.")

refresh_enabled = st.sidebar.checkbox("Enable Live Updates (5m)", value=True)
if refresh_enabled:
    count = st_autorefresh(interval=300 * 1000, key="datarefresh")
date_range = st.sidebar.date_input("Analysis Range", [datetime.now() - timedelta(days=1), datetime.now()])
if len(date_range) == 2:
    start_date, end_date = date_range
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    
    days_range = (end_dt - start_dt).days
    if timeframe_label == "1 Minute" and days_range > 7:
        st.warning("Note: 1-minute price data might be slow to fetch for long ranges.")
    if timeframe_label == "5 Minutes" and days_range > 60:
         st.warning("Note: 5-minute price data is limited to ~60 days.")
    with st.spinner('Crunching numbers...'):
        raw_df, hourly_df = load_and_process_data(start_dt, end_dt, resample_freq=resample_freq)

    # --- STRATEGY SETTINGS (SIDEBAR) ---
    st.sidebar.markdown("---")
    st.sidebar.header("Strategy Configuration")
    strategy_type_sel = st.sidebar.radio("Strategy Type", ["Crossover", "Spike Reversion"], index=1)
    std_mult = 2.0
    if strategy_type_sel == "Spike Reversion":
        std_mult = st.sidebar.slider("Spike Sensitivity (StdDev)", 1.0, 4.0, 2.0, 0.1, help="Higher = Fewer, more extreme spikes only.")


    # Chart Visibility Controls (Moved to Top)


    # Map selection to internal code
    algo_type = 'crossover' if strategy_type_sel == "Crossover" else 'spike'

    with st.spinner('Fetching Price Data...'):
        price_df = fetch_btc_price_analysis(start_dt, end_dt, interval=api_interval)
    if price_df.empty:
        st.warning("Insufficient Price Data from Binance. Please check your internet connection or date range.")
    else:
        price_df.index = price_df.index.tz_localize(None) 
        
        if hourly_df.empty:
            hourly_df = pd.DataFrame(columns=['BTC', 'USDT']) 
        
        combined_df = price_df[['Close', 'pct_change']].join(hourly_df, how='left')
        combined_df['BTC'] = combined_df['BTC'].fillna(0)
        combined_df['rolling_btc'] = combined_df['BTC'].rolling(f'{inflow_rolling_window}min').sum()
        
        combined_df['next_hour_return'] = combined_df['pct_change'].shift(-1)
        valid_corr_df = combined_df.dropna()
        
        if not raw_df.empty:
            usdt_count = len(raw_df[raw_df['currency'] == 'USDT'])
            btc_count = len(raw_df[raw_df['currency'] == 'BTC'])
        else:
            usdt_count = 0; btc_count = 0
        has_correlation_data = not hourly_df.empty and len(valid_corr_df) > 5
        
        if has_correlation_data:
            # Simple correlation between BTC Inflow and Price Change
            corr_coef = valid_corr_df['rolling_btc'].corr(valid_corr_df['next_hour_return'])
            if corr_coef < -0.3: corr_text = "Negative (Bearish - Supporting Hypothesis)"
            elif corr_coef > 0.3: corr_text = "Positive (Bullish - Contradicting)"
            else: corr_text = "Neutral / No Correlation"
            corr_display = f"{corr_coef:.2f}"; corr_help = corr_text
        else:
            corr_display = "N/A"; corr_help = "Not enough data points (>5) for correlation."
        c1, c2, c3 = st.columns(3)
        btc_sum = hourly_df['BTC'].sum() if not hourly_df.empty else 0
        
        c1.metric("Net BTC Inflow", f"${btc_sum:,.0f}", f"{btc_count} Events", delta_color="inverse")
        c2.metric("Predictive Correlation (r)", corr_display, delta=None, help=corr_help)
        last_price = price_df['Close'].iloc[-1]
        c3.metric("Current BTC Price", f"${last_price:,.2f}")
        
        # --- STRATEGY SIMULATION (CALCULATION & UI) ---
        trades_df = pd.DataFrame()
        selected_trade = None
        
        trades_df = pd.DataFrame()
        selected_trade = None


        # --- CHART GENERATION FUNCTION ---
        def create_inflow_chart(chart_df, avg_window, title_suffix, s_type='crossover', mult=2.0, visible_layers=None):
            if visible_layers is None:
                visible_layers = {'inflow': True, 'avg': True, 'spike': True, 'price': True}
                
            # Calculate specific rolling average for this chart
            mov_avg_col = f'avg_{avg_window}m'
            w_size = avg_window if timeframe_label == "1 Minute" else max(1, int(avg_window / 5))
            chart_df[mov_avg_col] = chart_df['rolling_btc'].rolling(window=w_size, min_periods=1).mean()

            # Smart Label
            if avg_window >= 60 and avg_window % 60 == 0:
                avg_label = f"{int(avg_window/60)}h"
            else:
                avg_label = f"{avg_window}m"

            # Single Chart with Dual Axis
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            
            # 1. Inflow (Primary Y - Left) using Bars or Filled Area
            if visible_layers.get('inflow', True):
                fig.add_trace(go.Scatter(
                    x=chart_df.index, y=chart_df['rolling_btc'], name="BTC Inflow", mode='lines',
                    line=dict(color='#EF553B', width=2), fill='tozeroy', fillcolor='rgba(239, 85, 59, 0.15)',
                    hovertemplate="<b>BTC Inflow</b><br>Time: %{x}<br>Total: $%{y:,.0f}<extra></extra>", legendgroup="Inflows"
                ), secondary_y=False)

            # 2. Avg Line (Primary Y - Left)
            if visible_layers.get('avg', True):
                fig.add_trace(go.Scatter(
                    x=chart_df.index, y=chart_df[mov_avg_col], 
                    name=f"{avg_label} Avg", mode='lines',
                    line=dict(color='white', width=1, dash='dash'),
                    hovertemplate=f"<b>{avg_label} Avg</b>: $%{'{y:,.0f}'}<extra></extra>", legendgroup="Inflows"
                ), secondary_y=False)

            # 3. Upper Band for Spike Strategy (Primary Y - Left)
            if s_type == 'spike' and visible_layers.get('spike', True):
                 w_s = avg_window if timeframe_label == "1 Minute" else max(1, int(avg_window / 5))
                 rolling_std = chart_df['rolling_btc'].rolling(window=w_s, min_periods=1).std()
                 upper_band = chart_df[mov_avg_col] + (rolling_std * mult)
                 
                 fig.add_trace(go.Scatter(
                    x=chart_df.index, y=upper_band,
                    name=f"Spike Threshold (+{mult}σ)", mode='lines',
                    line=dict(color='red', width=1, dash='dot'),
                    hovertemplate=f"<b>Spike Limit</b>: $%{'{y:,.0f}'}<extra></extra>", legendgroup="Inflows"
                 ), secondary_y=False)

            # 4. Price Line (Secondary Y - Right) - Draw ON TOP
            if visible_layers.get('price', True):
                fig.add_trace(go.Scatter(
                    x=chart_df.index, y=chart_df['Close'], name="BTC Price",
                    line=dict(color='#AC64FF', width=2), 
                    hovertemplate="<b>BTC Price</b>: $%{y:,.2f}<extra></extra>",
                    legendgroup="Price"
                ), secondary_y=True)

            # Anomalies (Primary Y - mapped to Inflow values)
            std_dev = chart_df['rolling_btc'].std()
            anomalies = chart_df[chart_df['rolling_btc'] > (2 * std_dev)]
            if not anomalies.empty:
                fig.add_trace(go.Scatter(
                    x=anomalies.index, y=anomalies['rolling_btc'], mode='markers', name='High Vol Signal',
                    marker=dict(color='yellow', size=6, symbol='star'),
                    showlegend=False,
                    legendgroup="Signals"
                ), secondary_y=False)

            # Annotation (Last Price) - Map to Secondary Y
            if not chart_df.empty:
                last_idx = chart_df.index.max()
                max_t = last_idx + timedelta(minutes=10)
                last_price_val = chart_df['Close'].iloc[-1]
                fig.add_annotation(
                    x=last_idx, y=last_price_val, xref="x", yref="y2", text=f"{last_price_val:,.2f}",
                    showarrow=True, arrowhead=0, ax=0, ay=-25,
                    bgcolor="#00CC96",
                    font=dict(color="white", size=12, family="monospace"), bordercolor="#2A2E39", borderwidth=1
                )
            else:
                max_t = datetime.utcnow() + timedelta(minutes=10)
            
            min_t = max_t - timedelta(hours=6)
            grid_interval_ms = 300000 if timeframe_label == "5 Minutes" else 60000
            
            # Y-Axis Ranges
            # Primary (Inflow)
            if not chart_df.empty:
                current_max_vol = chart_df['rolling_btc'].max()
                y_max_vol = max(100_000_000, current_max_vol * 1.2)
                
                # Secondary (Price) - Auto-scale
                # We won't calculate min/max manually, letting Plotly handle it for better fit
                pass
            else:
                y_max_vol = 100_000_000


            fig.update_layout(
                title_text=f"Inflow ({inflow_rolling_window}m Rolling) & Price Overlay {title_suffix}",
                dragmode="pan",
                hovermode="x unified", 
                height=900,  # Extended Vertically as requested
                template="plotly_dark",
                uirevision=f"{timeframe_label}_{start_date}_{end_date}_{avg_window}m_{s_type}",
                legend=dict(orientation="h", y=1.01, x=0.01), 
                paper_bgcolor="#131722", plot_bgcolor="#131722",
                xaxis=dict(gridcolor="#2A2E39", range=[min_t, max_t], title="Time", showgrid=True, tickmode='linear', dtick=grid_interval_ms),
                yaxis=dict(
                    title=dict(text=f"Inflow Volume ({inflow_rolling_window}m)", font=dict(color="#EF553B")), 
                    tickfont=dict(color="#EF553B"),
                    gridcolor="#2A2E39", range=[0, y_max_vol], side="left"
                ), 
                yaxis2=dict(
                    title=dict(text="BTC Price ($)", font=dict(color="#AC64FF")), 
                    tickfont=dict(color="#AC64FF"),
                    gridcolor="rgba(0,0,0,0)", # Hide secondary grid to avoid clutter
                    # range=None (Auto), 
                    side="right", overlaying="y"
                )
            )
            return fig


        # --- (MOVED UP) CHART RENDERING PLACEHOLDER ---
        # We need best_period from optimization first?
        # Optimization runs below. If we move chart up, we must use a CURRENT 'best_period' or the last known one.
        # But user wants chart *under* crossover options.
        # Let's run a "Preview" chart here using the DEFAULT (or current best if stored in session state).
        # Actually, optimization is fast now. We can run optimization FIRST (hidden/spinner), THEN render chart, THEN render metrics.
        # So we just re-order the blocks.

        # Strategy Optimization Block

        
        best_period = 100 # Default (Standard 20-period MA for 5m data)
        best_label = "100m" # Default
        
        if not combined_df.empty:
            # 1. Define Key Periods to Test (Optimized List)
            # From 15m to 24h (1440m) - Reducing iterations for speed
            test_periods = [15, 30, 45, 60, 90, 120, 240, 360, 480, 720, 1440]
            
            # 2. Run Optimization (Fast Vectorized)
            with st.spinner(f"Optimizing {strategy_type_sel} Strategy..."):
                results_df = optimize_strategy(combined_df.copy(), test_periods, strategy_type=algo_type, std_dev_mult=std_mult)
            
            if not results_df.empty:
                best_row = results_df.iloc[0]
                best_period = int(best_row['Period (min)'])
                best_return = best_row['Total Return']
                
                # Smart Label for display
                if best_period >= 60 and best_period % 60 == 0:
                    best_label = f"{int(best_period/60)}h"
                else:
                    best_label = f"{best_period}m"
                
                # Calculate dynamic average for the BEST period
                col_best = f'avg_{best_period}m'
                # Re-calc average for full DF (optimization copies it inside)
                w_size_best_viz = best_period if timeframe_label == "1 Minute" else max(1, int(best_period / 5))
                combined_df[col_best] = combined_df['rolling_btc'].rolling(window=w_size_best_viz, min_periods=1).mean()
                
                # Run Backtest with Best Period to get trades
                trades_df = run_backtest_simulation(combined_df, avg_col=col_best, strategy_type=algo_type, std_dev_mult=std_mult)

                # --- LAYOUT CONTAINERS ---
                cont_chart = st.container()
                st.markdown("---")
                cont_metrics = st.container()
                
                # --- METRICS & TABLE (Execution FIRST to capture selection, Display SECOND via container) ---
                # Wait, execution order matters for the WIDGET to return value?
                # Yes. st.dataframe must be called. But if we call it in `with cont_metrics`, it appears there.
                # Then we can use its output in `with cont_chart`?
                # YES. Because we are in the same script run.
                # 'cont_chart' is defined (created in DOM) *before* 'cont_metrics'.
                # We populate 'cont_metrics' first? 
                # No, if we populate 'cont_metrics' first in code, does it render first? 
                # No, it renders where the container was defined.
                # So:
                # 1. Define container_chart (Top).
                # 2. Define container_stats (Bottom).
                # 3. Populate container_stats (Code runs, widget renders at Bottom, returns 'event').
                # 4. Populate container_chart (Code runs, uses 'event', renders at Top).
                
                # THIS IS THE WAY.

                with cont_metrics:
                     # Display Best Result Text
                     st.success(f"🏆 **Best Strategy Found:** {best_label} Average (Return: {best_return:.2f}%)")
                     
                     with st.expander("View All Optimization Results"):
                         st.dataframe(results_df.style.format({'Total Return': '{:.2f}%', 'Win Rate': '{:.1f}%', 'Avg PnL': '{:.2f}%'}), use_container_width=True)

                     if algo_type == 'crossover':
                         st.caption(f"Strategy: Inflow > {best_label} Avg = SHORT | Inflow < {best_label} Avg = LONG")
                     else:
                         st.caption(f"Strategy: Inflow > {best_label} Avg + {std_mult}σ = SHORT | Inflow < {best_label} Avg = LONG")

                     if not trades_df.empty:
                        # Strategy Metrics
                        total_return = trades_df['PnL %'].sum()
                        win_count = len(trades_df[trades_df['Result'] == 'WIN'])
                        total_trades = len(trades_df)
                        win_rate = (win_count / total_trades) * 100
                        
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Total Return", f"{total_return:.2f}%", delta=f"{total_return:.2f}%")
                        m2.metric("Win Rate", f"{win_rate:.1f}%", f"{win_count}/{total_trades} Trades")
                        m3.metric("Avg PnL", f"{trades_df['PnL %'].mean():.2f}%")
                        
                        st.caption("👇 Select a trade to view entry/exit on chart")
                        
                        # Interactive Trade Log
                        event = st.dataframe(
                            trades_df.style.format({'Entry Price': '${:,.2f}', 'Exit Price': '${:,.2f}', 'PnL %': '{:,.2f}%'}),
                            use_container_width=True,
                            selection_mode="single-row",
                            on_select="rerun"
                        )
                        
                        if len(event.selection.rows) > 0:
                            selected_idx = event.selection.rows[0]
                            selected_trade = trades_df.iloc[selected_idx]
                            st.info(f"Viewing Trade: {selected_trade['Type']} at {selected_trade['Entry Time'].strftime('%H:%M')} -> {selected_trade['Result']}")

                with cont_chart:
                     # 1. Main Optimized Chart
                     # Header removed as requested

                     
                     v_layers = {
                        'inflow': show_inflow, 'avg': show_avg, 
                        'spike': show_spike, 'price': show_price
                     }
                     fig_optim = create_inflow_chart(combined_df.copy(), best_period, f"(with {best_label} Average)", s_type=algo_type, mult=std_mult, visible_layers=v_layers)

                     # Overlay Selected Trade (IF selected in bottom table)
                     if selected_trade is not None and show_trades:
                        entry_color = 'limegreen' if selected_trade['Type'] == 'LONG' else 'red'
                        entry_symbol = 'triangle-up' if selected_trade['Type'] == 'LONG' else 'triangle-down'
                        
                        # Entry
                        fig_optim.add_trace(go.Scatter(
                            x=[selected_trade['Entry Time']], y=[selected_trade['Entry Price']],
                            mode='markers', name='Trade Entry',
                            marker=dict(color=entry_color, size=14, symbol=entry_symbol, line=dict(color='white', width=2)),
                            legendgroup="Trade"
                        ), secondary_y=True)
                        
                        # Exit
                        fig_optim.add_trace(go.Scatter(
                            x=[selected_trade['Exit Time']], y=[selected_trade['Exit Price']],
                            mode='markers', name='Trade Exit',
                            marker=dict(color='white', size=10, symbol='x'),
                            legendgroup="Trade"
                        ), secondary_y=True)
                        
                        # Path
                        fig_optim.add_trace(go.Scatter(
                            x=[selected_trade['Entry Time'], selected_trade['Exit Time']],
                            y=[selected_trade['Entry Price'], selected_trade['Exit Price']],
                            mode='lines', name='Trade Path',
                            line=dict(color=entry_color, width=2, dash='dot'),
                            legendgroup="Trade"
                        ), secondary_y=True)

                     st.plotly_chart(fig_optim, width="stretch", key="optim_btc_chart")

    st.markdown("### Recent Webhook Logs")
    
    try:
        conn = sqlite3.connect(DB_FILE)
        logs_df = pd.read_sql_query("SELECT timestamp, currency, amount_usd, destination, raw_data FROM inflows ORDER BY timestamp DESC LIMIT 1000", conn)
        conn.close()
        
        if not logs_df.empty:
            btc_df = logs_df[logs_df['currency'] == 'BTC']
            st.markdown("---")
            
            st.subheader(":red[BTC Inflows]")
            if not btc_df.empty:
                now_utc = datetime.utcnow()
                for index, row in btc_df.iloc[:20].iterrows():
                    ts = pd.to_datetime(row['timestamp'])
                    if ts.tzinfo is not None:
                        ts = ts.tz_convert(None) 
                    
                    diff = now_utc - ts
                    
                    if diff < timedelta(hours=24):
                        total_seconds = int(diff.total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        
                        if hours > 0:
                            time_str = f"{hours}h {minutes}m ago"
                        else:
                            time_str = f"{minutes}m ago"
                    else:
                        time_str = ts.strftime('%H:%M:%S | %Y-%m-%d')
                        
                    summary = f"{time_str} | ${row['amount_usd']:,.0f} | -> {row['destination']}"
                    with st.expander(f":red[(BTC)] {summary}"):
                         try:
                             parsed = json.loads(row['raw_data'])
                             st.json(parsed)
                         except:
                             st.code(row['raw_data'], language='text')
            else: st.info("No BTC Inflows yet.")
        else:
            st.info("No logs found yet.")
            
    except Exception as e:
        st.error(f"Error loading logs: {e}")
    st.markdown("### Skipped / Ignored Alerts")
    try:
        conn = sqlite3.connect(DB_FILE)
        skipped_df = pd.read_sql_query("SELECT timestamp, reason, raw_data FROM skipped_inflows ORDER BY timestamp DESC LIMIT 100", conn)
        conn.close()
        if not skipped_df.empty:
            for index, row in skipped_df.iloc[:10].iterrows():
                ts_str = pd.to_datetime(row['timestamp']).strftime('%H:%M:%S')
                with st.expander(f"{ts_str} | Reason: {row['reason']}"):
                    try:
                        parsed = json.loads(row['raw_data'])
                        st.json(parsed)
                    except:
                        st.code(row['raw_data'], language='text')
        else:
            st.info("No skipped alerts recorded.")
    except Exception as e:
        if "no such table" in str(e): st.info("Initializing...")
        else: st.error(f"Error loading skipped logs: {e}")
    with st.expander("Detailed Data View"):
        st.dataframe(combined_df.style.format({'BTC': '${:,.0f}', 'Close': '${:,.2f}'}))
else:
    st.info("Select a date range to begin.")

# --- SIDEBAR FOOTER (Models Status) ---
st.sidebar.markdown("---")
st.sidebar.markdown("**System Status**")

# Moved Webhook Config Here
st.sidebar.markdown("**[Config] Webhook Configuration**")
if current_url and "ngrok" in current_url: # basic check if we detected ngrok
    st.sidebar.success("[OK] Ngrok Detected")
else:
    # If we didn't detect ngrok, we might want to allow input here?
    # But streamlit execution flow is linear. If we input here, 'current_url' changes here.
    # Checks above might have run with OLD value?
    # Actually, for just DISPLAYING status, it matches.
    pass

if current_url:
    st.sidebar.markdown("**Your Webhook URL:**")
    st.sidebar.code(f"{current_url.rstrip('/')}/webhook", language="text")
    st.sidebar.caption("Copy this to Arkham Alerts")
else:
    st.sidebar.warning("No Webhook URL detected.")

st.sidebar.info(f"**active_url:** `{current_url}`" if current_url else "Checking...")

# Check Local Server
try:
    r_local = requests.get("http://localhost:8000/", timeout=1)
    if r_local.status_code == 200:
        st.sidebar.success("✅ Local Server: Online")
    else:
        st.sidebar.error(f"❌ Local Server: {r_local.status_code}")
except:
    st.sidebar.error("❌ Local Server: Offline")

# Check Tunnel
if current_url:
    try:
        tunnel_base = current_url.replace("/webhook", "")
        r_tunnel = requests.get(tunnel_base, timeout=3)
        # 404/403/200 usually means it reached the server or at least the tunnel endpoint
        if r_tunnel.status_code in [200, 404, 403, 405, 502]: 
                st.sidebar.success("✅ Tunnel: Active")
        else:
                st.sidebar.warning(f"⚠️ Tunnel: {r_tunnel.status_code}")
    except:
        st.sidebar.error("❌ Tunnel: Unreachable")
