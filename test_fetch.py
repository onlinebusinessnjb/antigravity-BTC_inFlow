
import ccxt
import pandas as pd
from datetime import datetime, timedelta

def fetch_btc_price_analysis(start_dt, end_dt, interval='1m'):
    """
    Fetches OHLCV data from Binance via CCXT.
    Optimized to minimize calls.
    """
    try:
        # Use public API via CCXT (no keys needed for public data)
        exchange = ccxt.binance({'enableRateLimit': True})
        
        # Buffer start time slightly to ensure coverage or indicators
        since = int((start_dt - timedelta(minutes=60)).timestamp() * 1000)
        end_ts = int(end_dt.timestamp() * 1000)
        
        print(f"Fetching from {since} to {end_ts} with interval {interval}")
        
        all_ohlcv = []
        
        # Limit loop to preventing infinite hanging
        # 1000 candles * 5m = 5000 mins ~ 3.5 days per call.
        # Should be fast for 1-7 days.
        while True:
            print(f"Requesting since={since}")
            ohlcv = exchange.fetch_ohlcv('BTC/USDT', interval, since=since, limit=1000)
            if not ohlcv:
                print("No data returned")
                break
            
            print(f"Received {len(ohlcv)} candles. Last timestamp: {ohlcv[-1][0]}")
            
            all_ohlcv.extend(ohlcv)
            last_ts = ohlcv[-1][0]
            
            if last_ts >= end_ts or len(ohlcv) < 1000:
                break
                
            since = last_ts + 1 # Next ms
            
        if not all_ohlcv:
            return pd.DataFrame()
            
        columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        df = pd.DataFrame(all_ohlcv, columns=columns)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        # Filter exact range
        mask = (df.index >= start_dt) & (df.index <= end_dt)
        return df.loc[mask]
        
    except Exception as e:
        print(f"Price Fetch Error: {e}")
        return pd.DataFrame()

if __name__ == "__main__":
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1)
    
    print(f"Testing fetch from {start_date} to {end_date}")
    df = fetch_btc_price_analysis(start_date, end_date, interval='5m')
    print("\nResult:")
    print(df.head())
    print(f"\nShape: {df.shape}")
