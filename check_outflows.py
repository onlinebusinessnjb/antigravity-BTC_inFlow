
import sqlite3
import pandas as pd
import json

DB_FILE = "inflows.db"

def check_outflows():
    conn = sqlite3.connect(DB_FILE)
    
    print("--- CHECKING SKIPPED_INFLOWS ---")
    try:
        skipped = pd.read_sql_query("SELECT timestamp, reason, raw_data FROM skipped_inflows", conn)
        # Filter for outflow in reason or raw_data
        outflow_skipped = skipped[skipped['reason'].str.contains('outflow', case=False, na=False) | 
                                  skipped['raw_data'].str.contains('outflow', case=False, na=False)]
        
        if not outflow_skipped.empty:
            print(f"Found {len(outflow_skipped)} skipped outflow alerts:")
            print(outflow_skipped[['timestamp', 'reason']].head(10))
        else:
            print("No skipped outflow alerts found.")
    except Exception as e:
        print(f"Error checking skipped: {e}")

    print("\n--- CHECKING PROCESSED INFLOWS (Alerts accepted as BTC) ---")
    try:
        # Check if they were accepted but labeled as BTC
        inflows = pd.read_sql_query("SELECT timestamp, amount_usd, raw_data FROM inflows WHERE currency='BTC'", conn)
        
        # Check raw_data for 'outflow'
        outflow_accepted = inflows[inflows['raw_data'].str.contains('outflow', case=False, na=False)]
        
        if not outflow_accepted.empty:
            print(f"Found {len(outflow_accepted)} ACCEPTED outflow alerts (treated as BTC inflows):")
            print(outflow_accepted[['timestamp', 'amount_usd']].head(10))
            
            # Show first one to confirm structure
            print("\nSample Alert Name from first match:")
            try:
                data = json.loads(outflow_accepted.iloc[0]['raw_data'])
                print(f"Alert Name: {data.get('alertName')}")
            except:
                print("Could not parse JSON")
        else:
            print("No accepted outflow alerts found.")
            
    except Exception as e:
        print(f"Error checking inflows: {e}")
        
    conn.close()

if __name__ == "__main__":
    check_outflows()
