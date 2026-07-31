"""
Tool: query_tickets_db
Lets the agent run READ-ONLY SQL against the sample support_tickets.db.
Guardrails: only a single SELECT statement is allowed, no writes,
no multiple statements, opened in SQLite read-only ("mode=ro") URI mode
as a second line of defense.
"""
import os
import re
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "support_tickets.db")

SCHEMA_DESCRIPTION = (
    "Table tickets(id INTEGER, title TEXT, status TEXT ['open','in_progress','closed'], "
    "priority TEXT ['low','medium','high','critical'], assignee TEXT, created_at TEXT ISO8601)"
)

TOOL_SCHEMA = {
    "name": "query_tickets_db",
    "description": (
        "Run a read-only SQL SELECT query against the support tickets database. "
        f"Schema: {SCHEMA_DESCRIPTION}. Only SELECT statements are permitted."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "A single SQL SELECT statement, e.g. \"SELECT title, priority FROM tickets WHERE status = 'open'\"",
            }
        },
        "required": ["sql"],
    },
}

_SELECT_ONLY = re.compile(r"^\s*SELECT\s", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|PRAGMA)\b", re.IGNORECASE
)


def run(sql: str) -> dict:
    sql = sql.strip().rstrip(";")

    if ";" in sql:
        return {"error": "Only a single statement is allowed (no semicolons)."}
    if not _SELECT_ONLY.match(sql):
        return {"error": "Only SELECT statements are allowed."}
    if _FORBIDDEN.search(sql):
        return {"error": "Query contains a forbidden write/schema keyword."}
    if not os.path.exists(DB_PATH):
        return {"error": "Database not initialized. Run `python db/init_db.py` first."}

    try:
        uri = f"file:{DB_PATH}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchmany(50)]  # cap result size
        conn.close()
        return {"row_count": len(rows), "rows": rows}
    except sqlite3.Error as e:
        return {"error": f"SQL error: {e}"}
