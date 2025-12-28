
import pandas as pd
import numpy as np

# Simulate 5-minute data
dates = pd.date_range(start='2024-01-01 12:00', periods=5, freq='5min')
df = pd.DataFrame({'BTC': [10, 10, 10, 10, 10]}, index=dates)

print("--- Data (5min freq) ---")
print(df)

print("\n--- Rolling 1min ---")
print(df['BTC'].rolling('1min').sum())

print("\n--- Rolling 5min ---")
print(df['BTC'].rolling('5min').sum())

print("\n--- Rolling 6min ---")
print(df['BTC'].rolling('6min').sum())
