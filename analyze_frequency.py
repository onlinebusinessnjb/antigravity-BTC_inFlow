import sqlite3
import pandas as pd
import numpy as np

DB_FILE = "inflows.db"

def analyze():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT timestamp, amount_usd FROM inflows ORDER BY timestamp ASC", conn)
    conn.close()
    
    if df.empty:
        print("No data in database.")
        return

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Calculate Time Deltas (Time between alerts)
    df['delta'] = df['timestamp'].diff().dt.total_seconds() / 60.0 # Minutes
    
    print(f"Total Alerts: {len(df)}")
    print(f"Time Span: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    mean_delta = df['delta'].mean()
    median_delta = df['delta'].median()
    max_delta = df['delta'].max()
    
    print(f"\n--- ALERT FREQUENCY ---")
    print(f"Mean Time Between Alerts: {mean_delta:.2f} min")
    print(f"Median Time Between Alerts: {median_delta:.2f} min")
    
    # Analyze Burstiness (How many alerts happen within 15 min windows?)
    # Resample to 15m and count
    df_15m = df.set_index('timestamp').resample('15min').count()
    avg_per_15m = df_15m['amount_usd'].mean()
    zero_periods = (df_15m['amount_usd'] == 0).sum()
    total_periods = len(df_15m)
    
    print(f"\n--- BURSTINESS (15m Windows) ---")
    print(f"Avg Alerts per 15m: {avg_per_15m:.1f}")
    print(f"Quiet Periods (0 alerts): {zero_periods} / {total_periods} ({(zero_periods/total_periods)*100:.1f}%)")
    
    # Recommendation Logic
    rec_smooth = max(5, int(mean_delta * 3)) # Smooth at least 3x the average gap
    
    print(f"\n--- RECOMMENDATION ---")
    print(f"Recommended Smoothing: {rec_smooth} min (approx 3x Mean Frequency)")

if __name__ == "__main__":
    analyze()
