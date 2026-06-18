import os
import sqlite3
import time
from datetime import datetime


DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT DEFAULT '',
            source_type TEXT DEFAULT '',
            file_path TEXT DEFAULT '',
            md_path TEXT DEFAULT '',
            created_at REAL NOT NULL,
            duration_seconds REAL DEFAULT 0,
            char_count INTEGER DEFAULT 0,
            summary_granularity TEXT DEFAULT 'standard',
            vision_enabled INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def add_record(title, url="", source_type="", file_path="",
               md_path="", duration_seconds=0, char_count=0,
               summary_granularity="standard", vision_enabled=False):
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO records
               (title, url, source_type, file_path, md_path,
                created_at, duration_seconds, char_count,
                summary_granularity, vision_enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, url, source_type, file_path, md_path,
             time.time(), duration_seconds, char_count,
             summary_granularity, 1 if vision_enabled else 0),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_records(limit=100, offset=0):
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM records ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_record(record_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def delete_record(record_id):
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        conn.commit()
    finally:
        conn.close()


def get_total_count():
    conn = _get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM records").fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    d["created_at_str"] = datetime.fromtimestamp(d["created_at"]).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    return d
