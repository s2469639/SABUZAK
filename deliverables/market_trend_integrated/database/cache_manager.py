import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'market_trend_cache.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trend_cache (
            cache_key TEXT PRIMARY KEY,
            payload TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_cache(cache_key: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT payload FROM trend_cache WHERE cache_key = ? AND created_at > datetime('now', '-1 day')", (cache_key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None

def set_cache(cache_key: str, payload: dict):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO trend_cache (cache_key, payload)
        VALUES (?, ?)
    ''', (cache_key, json.dumps(payload, ensure_ascii=False)))
    conn.commit()
    conn.close()

