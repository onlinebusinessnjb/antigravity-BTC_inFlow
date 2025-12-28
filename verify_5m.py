
import ccxt
from datetime import datetime, timedelta

def verify_latest_price():
    exchange = ccxt.binance()
    # Fetch last 2 candles of 5m
    ohlcv = exchange.fetch_ohlcv('BTC/USDT', '5m', limit=2)
    for candle in ohlcv:
        ts = datetime.fromtimestamp(candle[0]/1000)
        close = candle[4]
        print(f"Time: {ts} | Close: {close}")

if __name__ == "__main__":
    verify_latest_price()
