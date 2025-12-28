
import pandas as pd
import numpy as np

def test_lagged_logic():
    print("Testing Lagged Logic...")
    
    # Mock Data: 2 Hours of 5min data (24 periods)
    # T=0 to T=120 mins
    timestamps = pd.date_range(start='2025-01-01 10:00', periods=25, freq='5min')
    df = pd.DataFrame({'BTC': [100.0] * 25}, index=timestamps)
    
    # Introduce a spike at 10:00 (T=0)
    df.loc['2025-01-01 10:00', 'BTC'] = 5000.0
    
    # Apply Rolling Window (e.g. 5 min sum)
    window_min = 5
    df['rolling_btc'] = df['BTC'].rolling(f'{window_min}min').sum()
    
    # --- PROPOSED LOGIC ---
    freq_str = '5min'
    
    if freq_str == '1min':
        shift_periods = 60
    elif freq_str == '5min':
        shift_periods = int(60 / 5) # 12
    else:
        shift_periods = 1
        
    print(f"Frequency: {freq_str} -> Shift Periods: {shift_periods}")
    
    df['lagged_1h'] = df['rolling_btc'].shift(shift_periods)
    
    # Check T=0 (10:00) -> Should be NaN (no data before)
    # Check T=60m (11:00) -> Should equal T=0 value
    
    val_t0 = df.loc['2025-01-01 10:00', 'rolling_btc']
    val_t60 = df.loc['2025-01-01 11:00', 'lagged_1h']
    
    print(f"T=10:00 (Original): {val_t0}")
    print(f"T=11:00 (Lagged):   {val_t60}")
    
    if val_t0 == val_t60:
        print("PASS: Logic correctly shifted by 1 hour.")
    else:
        print("FAIL: Values do not match.")
        
    print("\nDataFrame Head:")
    print(df.head())
    print("\nDataFrame Middle (Shift Target):")
    print(df.iloc[10:15])

if __name__ == "__main__":
    test_lagged_logic()
