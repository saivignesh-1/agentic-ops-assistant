"""
Creates a sample SQLite database (support_tickets.db) so the agent has
something real to query. Run once: `python db/init_db.py`
"""
import sqlite3
import os
from datetime import datetime, timedelta, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "support_tickets.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open', 'in_progress', 'closed')),
    priority TEXT NOT NULL CHECK(priority IN ('low', 'medium', 'high', 'critical')),
    assignee TEXT,
    created_at TEXT NOT NULL
);
"""

SAMPLE_ROWS = [
    ("Login page throws 500 on mobile Safari", "open", "high", "priya", 2),
    ("Add dark mode toggle", "open", "low", None, 10),
    ("Database connection pool exhausted under load", "in_progress", "critical", "arjun", 1),
    ("Typo in onboarding email", "closed", "low", "priya", 20),
    ("Export to CSV missing timezone column", "open", "medium", "sam", 5),
    ("API rate limiting not enforced on /search", "in_progress", "high", "arjun", 3),
    ("Slack notifications delayed by ~10 minutes", "closed", "medium", "sam", 15),
    ("Memory leak in background worker", "open", "critical", None, 0),
]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(SCHEMA)
    cur.execute("SELECT COUNT(*) FROM tickets")
    if cur.fetchone()[0] == 0:
        now = datetime.now(timezone.utc)
        for title, status, priority, assignee, days_ago in SAMPLE_ROWS:
            created_at = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
            cur.execute(
                "INSERT INTO tickets (title, status, priority, assignee, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (title, status, priority, assignee, created_at),
            )
        conn.commit()
        print(f"Seeded {len(SAMPLE_ROWS)} sample tickets into {DB_PATH}")
    else:
        print(f"Database already populated at {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    init_db()
