# Agentic Ops Assistant

A small agent that doesn't just answer questions (RAG-style retrieval) — it **takes actions**:
it checks live GitHub issue status, queries an internal database, calls a public weather
API, and — with explicit human approval — updates records in that database, chaining calls as needed to complete a request. Every reasoning step, tool call,
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

| Tool | What it does | Real or mocked? | Side effects? |
|---|---|---|---|
| `get_github_issue` | Looks up live status/labels/assignees of a GitHub issue or PR | Real (GitHub REST API, public, no auth needed for low volume) | Read-only |
| `query_tickets_db` | Read-only SQL over a sample support-tickets SQLite DB | Real DB, sample seed data | Read-only |
| `get_weather` | Current conditions for a city | Real (Open-Meteo, free, no API key) | Read-only |
| `update_ticket` | Changes a ticket's status and/or assignee | Real DB write | **Writes — requires human confirmation (see below)** |

The DB read tool is guarded: only single `SELECT` statements are accepted (regex-checked,
write/schema keywords blocked, and the SQLite connection itself is opened `mode=ro`)
so the agent can't be tricked into mutating data via prompt injection.

## Human-in-the-loop confirmation for writes

`update_ticket` is the one tool with a real side effect, and it's treated differently
from the rest: the model can *propose* calling it, but `agent.py` never executes it
automatically. Instead, `run_agent()` pauses mid-loop and returns a `PendingAction`
object describing exactly what it wants to do (tool name + arguments) instead of a
final answer.

The front end (CLI or Discord) is responsible for showing that proposal to a human and
calling `resume_agent(pending, approved=True/False, trace)` once they respond. Only
if approved does the write actually run — the result (or a "cancelled by user" note)
is then fed back to the model so it can give a final answer that reflects what really
happened, not what it assumed would happen.

- **CLI**: prompts with a plain `[y/N]` question in the terminal.
- **Discord**: posts the proposed action with ✅ / ❌ reactions and waits (60s timeout)
  for the original requester to react; a timeout counts as a rejection.

This means the model itself never has unmediated write access — every mutation passes
through a human checkpoint outside the model's control, which is the same pattern real
production agents use before taking any action with consequences (sending an email,
deploying code, charging a card, etc).

Try it:
```bash
python cli.py "Reassign ticket 3 to sam and mark it in_progress"
```

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

# one-shot, read-only
python cli.py "How many critical or high priority tickets are still open, and who owns them?"

python cli.py "What's the status of issue #1 on anthropics/anthropic-sdk-python?"

python cli.py "Check the weather in Hyderabad, and separately tell me which open tickets are unassigned."

# one-shot, triggers the write-confirmation flow
python cli.py "Reassign ticket 3 to sam and mark it in_progress"
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

`discord_bot_stub.py` wires the exact same `run_agent()` / `resume_agent()` functions
into a Discord `on_message` handler — the agent, tools, and trace logger don't change
at all. That's the point of keeping `agent.py` decoupled from any particular front end:

```bash
export DISCORD_BOT_TOKEN=...
export GEMINI_API_KEY=...
python discord_bot_stub.py
# in a channel: !agent what's the status of issue #1 on anthropics/anthropic-sdk-python?
# in a channel: !agent reassign ticket 3 to sam  <- triggers a ✅ / ❌ confirmation prompt
```

## Design notes / things worth highlighting in a writeup

- **Multi-step tool chaining**: the loop doesn't stop after one tool call — the model can
  use one tool's result to decide the next call (e.g. "check the DB, then decide whether
  to also check GitHub") up to `MAX_TURNS` (default 8) before it's forced to answer.
- **Human-in-the-loop for writes**: the model can *propose* a database write but never
  executes it directly — `run_agent()`/`resume_agent()` force every mutation through an
  explicit human approval step first (see above).
- **Guardrails, not blind trust**: the read-only DB tool enforces access at three layers
  (regex allow-list, forbidden-keyword check, SQLite `mode=ro`). Tool exceptions are caught
  and turned into an `{"error": ...}` result fed back to the model rather than crashing
  the process.
- **Observability**: the trace isn't just print statements — it's a structured `TraceLogger`
  that saves JSON, so you could build evals or a dashboard over `logs/*.json` later.
- **Swappable front end**: `agent.py` has no knowledge of CLI vs. Discord vs. anything else;
  `cli.py` and `discord_bot_stub.py` are both thin adapters around `run_agent()` /
  `resume_agent()`.
- **Resilient model selection**: Gemini model names get deprecated/retired often; instead
  of hardcoding one, `agent.py` tries a list of candidates and locks onto whichever one
  the account can actually reach, so a Google-side deprecation doesn't silently break the
  whole agent.

## Possible next steps

- Add retries/backoff on tool network errors.
- Build a small eval set (query -> expected tool sequence) and score trace logs against it.
- Add more write tools behind the same confirmation gate (e.g. creating a GitHub issue).
- Persist conversation memory per Discord channel/user instead of treating every message
  as a fresh session.
