import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS papers (
                id TEXT PRIMARY KEY, published TEXT NOT NULL,
                updated TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS screenings (
                paper_id TEXT NOT NULL REFERENCES papers(id),
                fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (paper_id, fingerprint)
            );
        """)

    def save(self, paper):
        with self.db:
            self.db.execute("""INSERT INTO papers VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET published=excluded.published,
                updated=excluded.updated, payload=excluded.payload
                WHERE excluded.updated >= papers.updated""",
                (paper["id"], paper["published"], paper["updated"], json.dumps(paper, ensure_ascii=False)))

    def papers(self, start=None, end=None, categories=()):
        rows = self.db.execute("""SELECT payload FROM papers
            WHERE (? IS NULL OR substr(published,1,10) >= ?)
              AND (? IS NULL OR substr(published,1,10) <= ?)
            ORDER BY published DESC, id""", (start, start, end, end))
        return [p for p in (json.loads(r[0]) for r in rows)
                if not categories or set(categories).intersection(p["categories"])]

    def result(self, paper_id, fingerprint):
        row = self.db.execute("SELECT payload FROM screenings WHERE paper_id=? AND fingerprint=?",
                              (paper_id, fingerprint)).fetchone()
        return json.loads(row[0]) if row else None

    def save_result(self, paper_id, fingerprint, result):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO screenings VALUES (?, ?, ?)",
                            (paper_id, fingerprint, json.dumps(result, ensure_ascii=False)))

    def close(self):
        self.db.close()
