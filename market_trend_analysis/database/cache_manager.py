import sqlite3
import json
from datetime import datetime, timedelta
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'market_trend_cache.db')

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cache (
                cache_key TEXT PRIMARY KEY,
                data TEXT,
                created_at TIMESTAMP
            )
        ''')
        conn.commit()

def get_cache(key: str):
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT data, created_at FROM cache WHERE cache_key = ?', (key,))
        row = cursor.fetchone()
        if row:
            data_str, created_at_str = row
            created_at = datetime.fromisoformat(created_at_str)
            if datetime.now() - created_at < timedelta(days=30):
                return json.loads(data_str)
            else:
                cursor.execute('DELETE FROM cache WHERE cache_key = ?', (key,))
                conn.commit()
    return None

def set_cache(key: str, data: dict):
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO cache (cache_key, data, created_at)
            VALUES (?, ?, ?)
        ''', (key, json.dumps(data, ensure_ascii=False), datetime.now().isoformat()))
        conn.commit()