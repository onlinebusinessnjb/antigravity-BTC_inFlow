
import sqlite3
import json
from datetime import datetime, timedelta, timezone
import random

DB_FILE = "inflows.db"

def inject_history():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Configuration
    hours_back = 10
    min_alerts = 15
    max_alerts = 25
    
    num_alerts = random.randint(min_alerts, max_alerts)
    btc_price_approx = 88_000.0
    
    print(f"Injecting {num_alerts} test alerts over the last {hours_back} hours...")
    
    now = datetime.now(timezone.utc)
    
    for i in range(num_alerts):
        # Random time in the last 10 hours
        offset_minutes = random.randint(1, hours_back * 60)
        timestamp = now - timedelta(minutes=offset_minutes)
        
        # Random amount between 100k and 15M
        usd = random.randint(100, 15000) * 1000
        btc_amount = usd / btc_price_approx
        
        destination = random.choice(['Binance', 'Coinbase', 'Kraken'])
        
        payload = {
            "alertName": "BTC_inFlow_History_Test",
            "event_data": {
                "tokenSymbol": "BTC",
                "valueUSD": usd,
                "tokenAmount": btc_amount,
                "toAddressLabel": destination,
                "blockTimestamp": timestamp.isoformat() + "Z", # Loose isoformat
                "transactionHash": f"mock_hist_{usd}_{i}"
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
            f"mock_hist_{usd}_{i}", 
            json.dumps(payload)
        ))
        
        print(f"Inserted: ${usd:,.0f} at {timestamp.strftime('%H:%M')} -> {destination}")

    conn.commit()
    conn.close()
    print("Historical injection complete.")

if __name__ == "__main__":
    inject_history()
