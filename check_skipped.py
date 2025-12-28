
import sqlite3
import pandas as pd

conn = sqlite3.connect('inflows.db')
try:
    df = pd.read_sql_query("SELECT * FROM skipped_inflows ORDER BY timestamp DESC LIMIT 5", conn)
    if not df.empty:
        print(df[['timestamp', 'reason', 'raw_data']].to_string())
    else:
        print("No skipped alerts found in database.")
except Exception as e:
    print(f"Error reading DB: {e}")
finally:
    conn.close()
