"""
Tool: update_ticket
The ONE tool in this project with real side effects (writes to the DB).
Because of that, it is never executed directly by agent.py -- it always
goes through a human-confirmation step first (see WRITE_TOOLS in agent.py).
"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "support_tickets.db")

VALID_STATUSES = ("open", "in_progress", "closed")

TOOL_SCHEMA = {
    "name": "update_ticket",
    "description": (
        "Update a support ticket's status and/or assignee. This makes a REAL change "
        "to the database and requires human confirmation before it takes effect. "
        "Use this when the user explicitly asks to reassign, close, or change the "
        "status of a specific ticket (by id)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticket_id": {"type": "integer", "description": "The id of the ticket to update"},
            "new_status": {
                "type": "string",
                "enum": list(VALID_STATUSES),
                "description": "New status for the ticket (optional if only reassigning)",
            },
            "new_assignee": {
                "type": "string",
                "description": "Username to assign the ticket to (optional if only changing status). "
                "Pass an empty string to unassign.",
            },
        },
        "required": ["ticket_id"],
    },
}


def run(ticket_id: int, new_status: str | None = None, new_assignee: str | None = None) -> dict:
    if new_status is None and new_assignee is None:
        return {"error": "Must provide at least one of new_status or new_assignee."}
    if new_status is not None and new_status not in VALID_STATUSES:
        return {"error": f"Invalid status '{new_status}'. Must be one of {VALID_STATUSES}."}
    if not os.path.exists(DB_PATH):
        return {"error": "Database not initialized. Run `python db/init_db.py` first."}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    before = cur.fetchone()
    if before is None:
        conn.close()
        return {"error": f"No ticket with id {ticket_id}"}

    updates, params = [], []
    if new_status is not None:
        updates.append("status = ?")
        params.append(new_status)
    if new_assignee is not None:
        updates.append("assignee = ?")
        params.append(new_assignee if new_assignee != "" else None)
    params.append(ticket_id)

    cur.execute(f"UPDATE tickets SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()

    cur.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    after = cur.fetchone()
    conn.close()

    return {
        "ticket_id": ticket_id,
        "before": dict(before),
        "after": dict(after),
    }
