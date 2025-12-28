
# native_app/data_manager.py
import sqlite3
import pandas as pd
import ccxt
from datetime import datetime, timedelta
import threading
import sys
import os

DB_FILE = "inflows.db"

def get_db_path():
    # If compiled with PyInstaller, we might want to look relative to the exe
    # But for now, user data is likely in the working directory or passed in.
    # We'll assume the same directory as the script/exe for simplicity,
    # or the parent directory if we are inside native_app/ during dev.
    if os.path.exists(DB_FILE):
        return DB_FILE
    if os.path.exists(os.path.join("..", DB_FILE)):
        return os.path.join("..", DB_FILE)
    return DB_FILE

class DataManager:
    def __init__(self):
        self.db_path = get_db_path()
        try:
            self.exchange = ccxt.binance({'enableRateLimit': True})
        except:
            self.exchange = None

    def fetch_data(self, days_lookback=1, timeframe="1m", rolling_window=5):
        """
        Fetches both Price and Inflow data, aligns them, and returns JSON-serializable lists.
        Blocking call (run in thread).
        """
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days_lookback)
        
        # 1. Fetch Price
        price_df = self._fetch_price(start_dt, end_dt, timeframe)
        
        # 2. Fetch Inflow
        inflow_df = self._fetch_inflow(start_dt, end_dt)
        
        # 3. Process Inflow
        if inflow_df.empty:
            processed_inflow = pd.DataFrame()
        else:
            # Resample
            freq_map = {"1m": "1min", "5m": "5min"}
            resample_freq = freq_map.get(timeframe, "1min")
            
            df_hourly = inflow_df.set_index('timestamp').groupby([pd.Grouper(freq=resample_freq), 'currency'])['amount_usd'].sum().unstack(fill_value=0)
            
            # Reindex to full range
            full_idx = pd.date_range(start=start_dt, end=end_dt, freq=resample_freq)
            df_hourly = df_hourly.reindex(full_idx, fill_value=0)
            
            if 'BTC' not in df_hourly.columns:
                df_hourly['BTC'] = 0.0
            
            processed_inflow = df_hourly.copy()
            processed_inflow['rolling_btc'] = processed_inflow['BTC'].rolling(f'{rolling_window}min').sum()
            processed_inflow['lagged_1h'] = processed_inflow['BTC'].rolling('60min', min_periods=1).sum().shift(1)

        # 4. Format for JS
        p_data = []
        if not price_df.empty:
            for ts, row in price_df.iterrows():
                p_data.append({
                    "time": int(ts.timestamp()),
                    "open": row['open'], "high": row['high'], "low": row['low'], "close": row['close']
                })
                
        i_data = []
        l_data = []
        
        if not processed_inflow.empty:
             for ts, row in processed_inflow.iterrows():
                t_val = int(ts.timestamp())
                val = row.get('rolling_btc', 0)
                lag = row.get('lagged_1h', 0)
                # Handle NaNs
                if pd.isna(val): val = 0
                if pd.isna(lag): lag = 0
                
                i_data.append({"time": t_val, "value": val})
                l_data.append({"time": t_val, "value": lag})

        return p_data, i_data, l_data

    def _fetch_price(self, start_dt, end_dt, interval):
        try:
            since = int(start_dt.timestamp() * 1000)
            all_ohlcv = []
            while True:
                ohlcv = self.exchange.fetch_ohlcv('BTC/USDT', interval, since=since, limit=1000)
                if not ohlcv: break
                all_ohlcv.extend(ohlcv)
                last_ts = ohlcv[-1][0]
                if last_ts >= int(end_dt.timestamp() * 1000) or len(ohlcv) < 1000: break
                since = last_ts + 1
            
            if not all_ohlcv: return pd.DataFrame()
            
            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return df
        except Exception as e:
            print(f"Price error: {e}")
            return pd.DataFrame()

    def _fetch_inflow(self, start_dt, end_dt):
        conn = sqlite3.connect(self.db_path)
        query = "SELECT * FROM inflows WHERE timestamp >= ? AND timestamp <= ?"
        try:
            df = pd.read_sql_query(query, conn, params=(str(start_dt), str(end_dt)))
            conn.close()
            if df.empty: return df
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed', utc=True).dt.tz_localize(None)
            mask = (df['timestamp'] >= start_dt) & (df['timestamp'] <= end_dt)
            return df.loc[mask]
        except Exception as e:
            print(f"DB Error: {e}")
            conn.close()
            return pd.DataFrame()

    def get_recent_inflows(self, limit=50):
        # Fetch logs for the UI sidebar
        conn = sqlite3.connect(self.db_path)
        try:
            df = pd.read_sql_query(f"SELECT timestamp, currency, amount_usd, destination FROM inflows WHERE currency='BTC' ORDER BY timestamp DESC LIMIT {limit}", conn)
            conn.close()
            return df
        except:
            conn.close()
            return pd.DataFrame()
