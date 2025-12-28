import sqlite3
import json
from datetime import datetime, timedelta

DB_FILE = "inflows.db"

def seed_specific_alerts():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Define exact test cases
    test_cases = [
        {"val": 100_000, "name": "Small Inflow"},
        {"val": 400_000, "name": "Medium Inflow"},
        {"val": 1_000_000, "name": "Large Inflow"},
        {"val": 3_000_000, "name": "Whale Inflow"}
    ]
    
    print("Injecting 4 specific test alerts...")
    
    base_time = datetime.now()
    
    for i, case in enumerate(test_cases):
        # Stagger them by 5 minutes backwards from now
        # 3M (Now), 1M (-5m), 400k (-10m), 100k (-15m)
        offsets = [15, 10, 5, 1] 
        event_time = base_time - timedelta(minutes=offsets[i])
        
        amount_usd = case["val"]
        payload = {
            "event_data": {
                "tokenSymbol": "BTC",
                "valueUSD": amount_usd,
                "toAddressLabel": "Binance",
                "blockTimestamp": event_time.isoformat()
            }
        }
        
        c.execute('''
            INSERT INTO inflows 
            (timestamp, currency, amount, amount_usd, destination, transaction_hash, raw_data) 
            VALUES (?, 'BTC', ?, ?, 'Binance', ?, ?)
        ''', (
            event_time, 
            amount_usd / 95000, # Approx BTC amount
            amount_usd, 
            f"tx_test_{i}", 
            json.dumps(payload)
        ))
        
        print(f"Inserted: ${amount_usd:,.0f} at {event_time.strftime('%H:%M:%S')}")

    conn.commit()
    conn.close()
    print("Done!")

if __name__ == "__main__":
    seed_specific_alerts()
