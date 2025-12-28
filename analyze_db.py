
import sqlite3
import pandas as pd
import json

DB_FILE = "inflows.db"

def analyze_database():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM inflows", conn)
    conn.close()
    
    print(f"Total Rows: {len(df)}")
    
    categories = {'IN': 0, 'OUT': 0, 'OTHER': 0, 'ERROR': 0}
    alert_names = {}
    
    for _, row in df.iterrows():
        try:
            raw = row['raw_data']
            data = json.loads(raw)
            name = data.get('alertName', 'Missing').strip()
            
            # Count distinct names
            alert_names[name] = alert_names.get(name, 0) + 1
            
            # Classify
            name_lower = name.lower()
            if "btc_inflow" in name_lower:
                categories['IN'] += 1
            elif "btc_outflow" in name_lower:
                categories['OUT'] += 1
            else:
                categories['OTHER'] += 1
        except:
            categories['ERROR'] += 1
            
    print("\n--- CLASSIFICATION STATS ---")
    for cat, count in categories.items():
        print(f"{cat}: {count}")
        
    print("\n--- DISTINCT ALERT NAMES ---")
    for name, count in alert_names.items():
        print(f"'{name}': {count}")

if __name__ == "__main__":
    analyze_database()
