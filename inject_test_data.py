
import sqlite3
import json
from datetime import datetime, timedelta
import random

DB_FILE = "inflows.db"

def inject_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    amounts_usd = [100_000, 500_000, 1_000_000, 4_000_000]
    btc_price_approx = 87_000.0
    
    print("Injecting test data...")
    now = datetime.utcnow()
    
    for i, usd in enumerate(amounts_usd):
        # Spread them out over the last 20 minutes
        # e.g. -18m, -13m, -8m, -3m
        offset_minutes = 18 - (i * 5) 
        timestamp = now - timedelta(minutes=offset_minutes)
        
        btc_amount = usd / btc_price_approx
        destination = random.choice(['Binance', 'Coinbase', 'Kraken'])
        
        payload = {
            "alertName": "BTC_inFlow_Test",
            "event_data": {
                "tokenSymbol": "BTC",
                "valueUSD": usd,
                "tokenAmount": btc_amount,
                "toAddressLabel": destination,
                "blockTimestamp": timestamp.isoformat() + "Z",
                "transactionHash": f"mock_tx_{usd}_{i}"
            }
        }
        
        c.execute('''
            INSERT INTO inflows (timestamp, currency, amount, amount_usd, destination, transaction_hash, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            timestamp, 
            "BTC", 
            btc_amount, 
            usd, 
            destination, 
            f"mock_tx_{usd}_{i}", 
            json.dumps(payload)
        ))
        
        print(f"Inserted: ${usd:,.0f} at {timestamp} -> {destination}")

    conn.commit()
    conn.close()
    print("Injection complete.")

if __name__ == "__main__":
    inject_data()
