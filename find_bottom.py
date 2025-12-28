
import sqlite3
import pandas as pd
import numpy as np
import ccxt
from datetime import datetime, timedelta

# --- CONFIG ---
DB_FILE = "inflows.db"

# --- 1. DATA LOADING ---
def get_data():
    conn = sqlite3.connect(DB_FILE)
    # Get all data for analysis
    df = pd.read_sql_query("SELECT * FROM inflows", conn)
    conn.close()
    
    if df.empty:
        print("No data in DB")
        return None, None

    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed', utc=True).dt.tz_localize(None)
    
    # Range: Let's look at the full dataset or last 2 days
    start_dt = df['timestamp'].min()
    end_dt = df['timestamp'].max()
    
    # Fetch Price
    # We need price to find the "Bottom"
    # Using CCXT to match dashboard logic
    exchange = ccxt.binance()
    timeframe = '5m'
    since = int(start_dt.timestamp() * 1000)
    limit = 1000
    
    all_ohlcv = []
    current_since = since
    
    print(f"Fetching Price Data from {start_dt} to {end_dt}...")
    
    while True:
        try:
            ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe, since=current_since, limit=limit)
            if not ohlcv:
                break
            all_ohlcv.extend(ohlcv)
            current_since = ohlcv[-1][0] + 1
            if len(ohlcv) < limit or pd.to_datetime(current_since, unit='ms') > end_dt + timedelta(hours=1):
                break
        except Exception as e:
            print(f"Error fetching price: {e}")
            break
            
    if not all_ohlcv:
        return None, None
        
    price_df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
    price_df['timestamp'] = pd.to_datetime(price_df['timestamp'], unit='ms')
    price_df.set_index('timestamp', inplace=True)
    
    # Resample Inflows to Hourly (base) then we re-roll
    df.set_index('timestamp', inplace=True)
    hourly_df = df.resample('5min').sum(numeric_only=True)
    
    # Debug print
    print("Hourly columns:", hourly_df.columns)
    
    # Combine
    combined = price_df[['Close']].join(hourly_df, how='left')
    
    if 'BTC' not in combined.columns:
        print("Warning: 'BTC' column missing after join. Creating with 0s.")
        combined['BTC'] = 0.0
        
    combined['BTC'] = combined['BTC'].fillna(0)
    
    return combined

# --- 2. FIND BOTTOM ---
def analyze_bottom_catcher(df):
    if df is None or df.empty:
        return

    # Find Global Min Price and its Time
    min_price_idx = df['Close'].idxmin()
    min_price = df['Close'].min()
    
    print(f"📉 Market Bottom Found: ${min_price:,.2f} at {min_price_idx}")
    
    # Search Space
    rolling_windows = [1, 5, 10, 15, 30, 60]
    ma_periods = [10, 20, 30, 45, 60, 90, 100, 120, 240, 360, 720, 1440]
    std_mults = [1.5, 2.0, 2.5, 3.0] # For Spike Reversion
    
    results = []

    # Iterate
    for rolling_m in rolling_windows:
        # Calculate Rolling Inflow
        col_roll = f'roll_{rolling_m}'
        # If window is 1m, we need 1m data? 
        # Our base df is 5m (resampled above). 
        # Actually dashboard logic resamples from raw.
        # If user wants 1m rolling, we need 1m resolution.
        # But for '5min' price candles, let's stick to 5m multiplier?
        # If user sets rolling=1m, but candles are 5m, it's just the 5m sum divided by 5?
        # dashboard: combined_df['BTC'].rolling(f'{inflow_rolling_window}min').sum()
        # Since our dataframe index is 5min freq, rolling('1min') is just looking at the row itself (5m block)? 
        # No, rolling by time works on datetime index.
        # But if rows are 5min apart, rolling('1min') will only see the current row (0 lookback).
        # rolling('10min') will see current + prev.
        # So rolling_m must be >= 5 to be meaningful on 5m candles.
        
        # Let's effectively treat rolling_m as "lookback matches"
        # dashboard uses: rolling(f'{w}min')
        
        # We need to re-calc 'rolling_btc' for this window
        # We need to make sure we don't error if window < 5m freq
        
        try:
             df['rolling_btc'] = df['BTC'].rolling(f'{rolling_m}min').sum()
        except:
             continue
             
        for ma_p in ma_periods:
            # Calculate MA
            # window size for mean
            # dashboard: w_size = max(1, int(ma_p / 5))
            w_size = max(1, int(ma_p / 5))
            ma_col = f'ma_{ma_p}'
            df[ma_col] = df['rolling_btc'].rolling(window=w_size).mean()
            
            # --- STRATEGY 1: CROSSOVER ---
            # Long when Inflow < Avg (Mean Reversion / Cool off?) 
            # OR User wants "Cross".
            # Usually: Inflow Crossing ABOVE Avg = Spike? Inflow Crossing BELOW Avg = Dip?
            # Standard Crossover in Dashboard:
            # Inflow < Avg -> LONG
            # Inflow > Avg -> SHORT
            
            # Check timestamps where Signal flips to LONG
            # Condition: (Inflow < Avg)
            cond_long = df['rolling_btc'] < df[ma_col]
            # Detect FLIP: False -> True
            # Shift 1: Previous was False (Inflow > Avg), Current is True.
            # This is the "Cross Under".
            entries = df[cond_long & (~cond_long.shift(1).fillna(False))]
            
            if not entries.empty:
                # Find closest entry to min_price_idx
                # Calculate time difference
                # abs(entry_time - min_price_time)
                
                # entries.index is DatetimeIndex
                # min_price_idx is Timestamp
                
                diffs = (entries.index - min_price_idx).abs()
                best_entry_idx = diffs.argmin()
                best_diff = diffs.iloc[best_entry_idx]
                
                # We want a signal BEFORE or AT the bottom ideally, or slightly after.
                # Distance is good metric.
                
                results.append({
                    'Type': 'Crossover',
                    'Rolling (m)': rolling_m,
                    'Avg Period (m)': ma_p,
                    'Mult': '-',
                    'Time Diff': best_diff,
                    'Closest Entry': entries.index[best_entry_idx]
                })

            # --- STRATEGY 2: SPIKE REVERSION ---
            # Long when (Inflow < Avg) AND (Prev was > Upper Band?)
            # Or dashboard logic:
            # Default Spike Logic:
            # Short if > Upper.
            # Long if < Avg.
            
            # So the LONG signal is the SAME for both strategies: Inflow < Avg.
            # The difference is the SHORT side.
            # The user asked about "White Line Cross" -> Average Cross.
            # So "Crossover" logic covers the "Average Cross".
            
            # Wait, "White line cross with lowest btc price".
            # The white line IS the average.
            # If "White line" crosses "Price"? No, scales are different.
            # If "White line" crosses "Inflow" at the bottom?
            
            # Yes, Inflow crossing Average (White Line) is the trigger.
            # So we just need to find the configuration where (Inflow < Average) happens closest to bottom.
            pass

    if not results:
        print("No signals found.")
        return

    # Sort by closest time diff
    results_df = pd.DataFrame(results)
    results_df.sort_values('Time Diff', inplace=True)
    
    print("\n🏆 BEST BOTTOM CATCHING CONFIGURATIONS:")
    print(results_df.head(5).to_string(index=False))
    
    best = results_df.iloc[0]
    print(f"\n💡 Recommendation: Set 'Inflow Rolling' to **{best['Rolling (m)']}m** and Strategy Period to **{best['Avg Period (m)']}m**.")
    print(f"   This triggered a signal at {best['Closest Entry']}, just {best['Time Diff']} away from the bottom.")

if __name__ == "__main__":
    df = get_data()
    analyze_bottom_catcher(df)
