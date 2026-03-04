import sqlite3
from pathlib import Path
from typing import List


class MemoryStore:
    def __init__(self, db_path: str = "runtime.db"):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                note TEXT NOT NULL,
                ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    def add(self, user_id: str, note: str):
        self.conn.execute("INSERT INTO memories(user_id, note) VALUES (?, ?)", (user_id, note))
        self.conn.commit()

    def search(self, user_id: str, query: str, limit: int = 5) -> List[str]:
        q = f"%{query}%"
        rows = self.conn.execute(
            "SELECT note FROM memories WHERE user_id=? AND note LIKE ? ORDER BY id DESC LIMIT ?",
            (user_id, q, limit),
        ).fetchall()
        return [r["note"] for r in rows]
