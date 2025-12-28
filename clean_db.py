
import sqlite3

DB_FILE = "inflows.db"

def clean_database():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    print("Cleaning database...")
    
    # Count before
    count_in = c.execute("SELECT COUNT(*) FROM inflows").fetchone()[0]
    count_skip = c.execute("SELECT COUNT(*) FROM skipped_inflows").fetchone()[0]
    print(f"Before: {count_in} inflows, {count_skip} skipped.")
    
    # Delete
    c.execute("DELETE FROM inflows")
    c.execute("DELETE FROM skipped_inflows")
    
    conn.commit()
    
    # VACUUM must be outside transaction (autocommit mode)
    # Reconnect for vacuum or just skip it if complex, but setting isolation_level=None works
    conn.isolation_level = None
    c.execute("VACUUM")
    
    conn.close()
    
    print("Database cleaned.")
    print("Final Count: 0")

if __name__ == "__main__":
    clean_database()
