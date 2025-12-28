
import sqlite3
import pandas as pd
import json

DB_FILE = "inflows.db"

def inspect_rows():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT id, raw_data FROM inflows LIMIT 5", conn)
    conn.close()
    
    print(f"Found {len(df)} rows.")
    for idx, row in df.iterrows():
        print(f"\n--- Row {row['id']} ---")
        try:
            data = json.loads(row['raw_data'])
            # Check if alertName exists
            if 'alertName' in data:
                print(f"✅ alertName found: {data['alertName']}")
            else:
                print(f"❌ alertName MISSING in raw_data keys: {list(data.keys())}")
        except:
            print("Invalid JSON")

if __name__ == "__main__":
    inspect_rows()
