# Agentic Ops Assistant

A small agent that doesn't just answer questions (RAG-style retrieval) — it **takes actions**:
it checks live GitHub issue status, queries an internal database, and calls a public weather
API, chaining calls together as needed to complete a request. Every reasoning step, tool call,
and tool result is written to a **trace log**, so the decision process is fully auditable.

Runs on the **free Gemini API** (Google AI Studio) — no billing required to get started.

This is Project 4 in the "chatbot -> RAG bot -> agent" progression: earlier bots retrieved and
answered; this one **decides what to do, does it, and shows its work**.

## Architecture

```
User query
    │
    ▼
┌─────────────────────────────────────────────┐
│  agent.py  — ReAct-style loop                │
│  1. Send query + tool schemas to Gemini       │
│  2. Gemini replies with reasoning text and/or │
│     a function_call request                   │
│  3. If function_call: execute the REAL tool,  │
│     feed result back, go to 1                 │
│  4. If plain text: that's the final answer    │
└─────────────────────────────────────────────┘
    │                    │                  │
    ▼                    ▼                  ▼
github_tool.py     database_tool.py    weather_tool.py
(GitHub REST API)  (read-only SQLite)  (Open-Meteo API)
    │                    │                  │
    └────────────────────┴──────────────────┘
                          │
                          ▼
                  trace_logger.py
        (records every step -> logs/*.json)
```

Each tool is a plain Python function with an Anthropic **tool schema** attached
(`TOOL_SCHEMA`) and a `run(...)` function. Adding a new capability means adding
one new file in `tools/` and registering it in `agent.py`'s `TOOLS` list and
`DISPATCH` dict — nothing else changes.

## Tools included

| Tool | What it does | Real or mocked? |
|---|---|---|
| `get_github_issue` | Looks up live status/labels/assignees of a GitHub issue or PR | Real (GitHub REST API, public, no auth needed for low volume) |
| `query_tickets_db` | Read-only SQL over a sample support-tickets SQLite DB | Real DB, sample seed data |
| `get_weather` | Current conditions for a city | Real (Open-Meteo, free, no API key) |

The DB tool is guarded: only single `SELECT` statements are accepted (regex-checked,
write/schema keywords blocked, and the SQLite connection itself is opened `mode=ro`)
so the agent can't be tricked into mutating data via prompt injection.

## Setup

1. Get a **free** API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) —
   no credit card required for the free tier.

```bash
cd agentic_project
pip install -r requirements.txt

# macOS/Linux
export GEMINI_API_KEY=your-key-here
# Windows PowerShell
$env:GEMINI_API_KEY = "your-key-here"

python db/init_db.py        # one-time: seeds support_tickets.db with sample tickets
```

## Run it

```bash
# interactive
python cli.py

# one-shot
python cli.py "How many critical or high priority tickets are still open, and who owns them?"

python cli.py "What's the status of issue #1 on anthropics/anthropic-sdk-python?"

python cli.py "Check the weather in Hyderabad, and separately tell me which open tickets are unassigned."
```

Every run prints a live trace like:

```
[01] THOUGHT       I need to check open critical tickets first.
[02] TOOL_CALL     query_tickets_db({"sql": "SELECT title, assignee FROM tickets WHERE status='open' AND priority='critical'"})
[03] TOOL_RESULT   -> {"row_count": 1, "rows": [{"title": "Memory leak in background worker", "assignee": null}]}
[04] THOUGHT       There's one open critical ticket and it's unassigned — I should flag that.
[05] FINAL_ANSWER  There is 1 open critical ticket ("Memory leak in background worker") and it has no assignee...
(full trace saved to logs/trace_2026-07-29T10-04-47.json)
```

and saves the full structured trace as JSON in `logs/` for later inspection or evals.

## Extending to Discord

`discord_bot_stub.py` wires the exact same `run_agent()` function into a Discord
`on_message` handler — the agent, tools, and trace logger don't change at all.
That's the point of keeping `agent.py` decoupled from any particular front end:

```bash
export DISCORD_BOT_TOKEN=...
export GEMINI_API_KEY=...
python discord_bot_stub.py
# in a channel: !agent what's the status of issue #1 on anthropics/anthropic-sdk-python?
```

## Design notes / things worth highlighting in a writeup

- **Multi-step tool chaining**: the loop doesn't stop after one tool call — the model can
  use one tool's result to decide the next call (e.g. "check the DB, then decide whether
  to also check GitHub") up to `MAX_TURNS` (default 8) before it's forced to answer.
- **Guardrails, not blind trust**: the DB tool enforces read-only access at three layers
  (regex allow-list, forbidden-keyword check, SQLite `mode=ro`). Tool exceptions are caught
  and turned into an `{"error": ...}` result fed back to the model rather than crashing
  the process.
- **Observability**: the trace isn't just print statements — it's a structured `TraceLogger`
  that saves JSON, so you could build evals or a dashboard over `logs/*.json` later.
- **Swappable front end**: `agent.py` has no knowledge of CLI vs. Discord vs. anything else;
  `cli.py` and `discord_bot_stub.py` are both thin adapters around `run_agent()`.

## Possible next steps

- Add a "confirm before acting" step for any tool with side effects (this project's tools
  are all read-only, but a real ops agent might also want to *create* a GitHub issue or
  *update* a ticket — those need a human-in-the-loop confirmation gate).
- Add retries/backoff on tool network errors.
- Build a small eval set (query -> expected tool sequence) and score trace logs against it.
