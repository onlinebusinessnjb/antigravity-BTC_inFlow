
import pandas as pd
import numpy as np

def test_avg_logic():
    print("Testing Historical Average Logic...")
    
    # Mock Data: 3 Hours of 5min data
    # T=0 to T=180 mins (36 periods)
    timestamps = pd.date_range(start='2025-01-01 10:00', periods=37, freq='5min')
    df = pd.DataFrame({'BTC': [100.0] * 37}, index=timestamps)
    
    # Rolling Window for Inflow (e.g. 5 min sum)
    window_min = 5
    df['rolling_btc'] = df['BTC'].rolling(f'{window_min}min').sum()
    
    # Spike at 10:30 (T=30m)
    df.loc['2025-01-01 10:30', 'rolling_btc'] = 1000.0
    
    # --- PROPOSED LOGIC ---
    # Average Inflow of last 60m excluding last 10m
    # 1. Shift by 10m (to exclude last 10m)
    # 2. Rolling 60m Mean
    
    offset_min = 10
    avg_window = 60
    freq_min = 5
    
    shift_periods = int(offset_min / freq_min) # 2 periods
    
    print(f"Freq: {freq_min}m | Shift: {shift_periods} periods | Window: {avg_window}m")
    
    # Shift to access data from T-10m downwards
    df['shifted'] = df['rolling_btc'].shift(shift_periods)
    
    # Calculate Mean of the 60m window ending at T-10m
    df['avg_baseline'] = df['shifted'].rolling(f'{avg_window}min').mean()
    
    # Verification
    # At T=35m (10:35), Shifted value is T=25m (100). Window is [T-85m to T-25m].
    # At T=40m (10:40), Shifted value is T=30m (1000). 
    # The spike (1000) enters 'avg_baseline' calculation at T=40m?
    # Window at T is (T-60m, T]. Applied to shifted data.
    # So at T=40m, shifted is T-10m=30m (Value 1000). 
    # Rolling window on Shifted at T includes Shifted[T]. Yes.
    
    print("\nData Slice (Around Spike at 10:30):")
    print(df.loc['2025-01-01 10:20':'2025-01-01 10:50', ['rolling_btc', 'shifted', 'avg_baseline']])
    
    # Check T=40m (10:40). 
    # Shifted = 1000. Window includes 1000 and previous 100s.
    # 60m window = 12 periods. Sum = 1000 + 11*100 = 2100. Mean = 2100/12 = 175.
    val_t40 = df.loc['2025-01-01 10:40', 'avg_baseline']
    expected = (1000 + 11*100) / 12
    
    print(f"\nValue at 10:40: {val_t40:.2f}")
    print(f"Expected:       {expected:.2f}")

    if abs(val_t40 - expected) < 0.01:
        print("PASS: Logic matches expectation.")
    else:
        print("FAIL: Values do not match.")

if __name__ == "__main__":
    test_avg_logic()
