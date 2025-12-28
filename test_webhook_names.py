import requests
import json
import sqlite3
import time

DB_FILE = "inflows.db"
WEBHOOK_URL = "http://localhost:8000/webhook"

test_names = [
    "BTC_inFlow-1-to-5",
    "BTC_inFlow-5",
    "BTC_inFlow-6-to-7",
    "SomeOther_BTC_inFlow_Name"
]

def check_db_for_payload(alert_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Check distinct currency for unprocessed/recent entries? 
    # Just check if we have an entry with raw_data containing this alertName
    # The raw_data stores the payload.
    # But wait, dashboard uses 'currency' column. We want to check if 'currency' is 'BTC' for this entry.
    
    # We'll check the last entry.
    cursor.execute("SELECT currency, raw_data FROM inflows ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    conn.close()
    
    for r in rows:
        curr = r[0]
        raw = r[1]
        if alert_name in raw:
            return curr
    return None

def run_test():
    for name in test_names:
        print(f"Testing alertName: {name}")
        payload = {
            "alertName": name,
            "transfer": {
                "transactionHash": f"hash_for_{name}",
                "valueUSD": 1000,
                "tokenAmount": 1,
                "blockTimestamp": "2025-01-01T12:00:00Z"
            }
        }
        
        try:
            r = requests.post(WEBHOOK_URL, json=payload)
            print(f"Status: {r.status_code}")
        except Exception as e:
            print(f"Request failed: {e}")
            continue
            
        # Give it a second to process (background task)
        time.sleep(1)
        
        # Check DB
        detected_currency = check_db_for_payload(name)
        if detected_currency == 'BTC':
            print(f"✅ Success: Alert '{name}' stored as BTC")
        else:
            print(f"❌ Failure: Alert '{name}' NOT found as BTC (Found: {detected_currency})")

if __name__ == "__main__":
    run_test()
