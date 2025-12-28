import sqlite3
DB_FILE = "inflows.db"
def reset_db():
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
    conn.commit()
    conn.close()
    print("Database reset successfully!")
if __name__ == "__main__":
    reset_db()
