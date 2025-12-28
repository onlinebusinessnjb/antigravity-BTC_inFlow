
import pandas as pd
import numpy as np

def verify_logic():
    # Setup time range
    rng = pd.date_range('2025-01-01 10:00', '2025-01-01 11:30', freq='5min')
    df = pd.DataFrame(index=rng)
    df['BTC'] = 0.0
    
    # Inject spikes
    # Small spike at 10:35
    df.loc['2025-01-01 10:35', 'BTC'] = 1_000_000
    
    # Big spike at 10:45
    df.loc['2025-01-01 10:45', 'BTC'] = 10_000_000
    
    # Logic from dashboard_v2.py
    inflow_rolling_window = 5
    resample_freq = '5min'
    shift_min = 10
    window_min = 60
    
    shift_periods = int(shift_min / 5) # 2
    
    # 1. Rolling Sum (Window for "Inflow" definition)
    df['rolling_btc'] = df['BTC'].rolling(f'{inflow_rolling_window}min').sum()
    
    # 2. Shift (Lag)
    df['shifted'] = df['rolling_btc'].shift(shift_periods)
    
    # 3. Rolling Mean (Baseline)
    df['avg_baseline'] = df['shifted'].rolling(f'{window_min}min').mean()
    
    # Display relevant rows
    print(df.loc['2025-01-01 10:30':'2025-01-01 11:10', ['BTC', 'shifted', 'avg_baseline']])

if __name__ == "__main__":
    verify_logic()
