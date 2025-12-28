import sqlite3
import random
from datetime import datetime, timedelta
import json
DB_FILE = "inflows.db"
def seed_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('DROP TABLE IF EXISTS inflows')
    c.execute('''
        CREATE TABLE inflows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            currency TEXT,
            amount REAL,
            amount_usd REAL,
            destination TEXT,
            transaction_hash TEXT,
            raw_data TEXT
        )
    ''')
    print("Seeding database with SMART mock data...")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=2)
    current_dt = start_date
    while current_dt <= end_date:
        regime = random.choices(['bear', 'bull'], weights=[0.4, 0.6])[0]
        num_events = random.randint(0, 3)
        for _ in range(num_events):
            event_time = current_dt + timedelta(seconds=random.randint(0, 290))
            if regime == 'bull': currency = random.choices(['USDT', 'BTC'], weights=[0.8, 0.2])[0]
            else: currency = random.choices(['BTC', 'USDT'], weights=[0.8, 0.2])[0]
            destination = random.choice(['Binance', 'Coinbase'])
            if currency == 'BTC': amount = random.uniform(2, 20); amount_usd = amount * 60000 
            else: amount = random.uniform(120_000, 2_000_000); amount_usd = amount
            mock_payload = {"event_data": {"tokenSymbol": currency, "valueUSD": amount_usd, "toAddressLabel": destination, "blockTimestamp": event_time.isoformat()}}
            c.execute('INSERT INTO inflows (timestamp, currency, amount, amount_usd, destination, transaction_hash, raw_data) VALUES (?, ?, ?, ?, ?, "mock_tx_seed", ?)', (event_time, currency, amount, amount_usd, destination, json.dumps(mock_payload)))
        current_dt += timedelta(minutes=5)
    conn.commit()
    conn.close()
    print("Database seeded!")
if __name__ == "__main__":
    seed_db()
