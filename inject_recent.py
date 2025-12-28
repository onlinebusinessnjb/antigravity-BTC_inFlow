
import sqlite3
import json
from datetime import datetime, timedelta
import random

DB_FILE = "inflows.db"

def inject_recent_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Random amounts for variety (between 500k and 10M)
    num_alerts = random.randint(3, 6)
    amounts_usd = [random.randint(500, 10000) * 1000 for _ in range(num_alerts)]
    
    btc_price_approx = 88_000.0
    
    print(f"Injecting {num_alerts} test alerts (last 2 minutes)...")
    # Use UTC now
    now = datetime.utcnow()
    
    for i, usd in enumerate(amounts_usd):
        # Inject spread over last 2 minutes
        offset_seconds = random.randint(5, 120)
        timestamp = now - timedelta(seconds=offset_seconds)
        
        btc_amount = usd / btc_price_approx
        destination = random.choice(['Binance', 'Coinbase'])
        
        payload = {
            "alertName": "BTC_inFlow_Recent_Test",
            "event_data": {
                "tokenSymbol": "BTC",
                "valueUSD": usd,
                "tokenAmount": btc_amount,
                "toAddressLabel": destination,
                "blockTimestamp": timestamp.isoformat() + "Z",
                "transactionHash": f"mock_recent_{usd}_{i}"
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
            f"mock_recent_{usd}_{i}", 
            json.dumps(payload)
        ))
        
        print(f"Inserted: ${usd:,.0f} at {timestamp} (UTC) -> {destination}")

    conn.commit()
    conn.close()
    print("Injection complete.")

if __name__ == "__main__":
    inject_recent_data()
