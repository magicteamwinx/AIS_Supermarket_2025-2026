import sqlite3
def get_db():
    conn = sqlite3.connect("zlagoda.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()