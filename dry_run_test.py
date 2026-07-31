"""
FREE dry run — no ANTHROPIC_API_KEY required.

This tests the real parts of the project that don't cost money:
  - the database tool (real local SQLite queries)
  - the GitHub tool (real public GitHub API call)
  - the trace logger

...and simulates ONE fake "LLM turn" so you can see the full agent loop
shape (thought -> tool_call -> tool_result -> final_answer) without
spending any API credits.

Run it with:
    py dry_run_test.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from tools import database_tool, github_tool
from trace_logger import TraceLogger

print("=" * 60)
print("1. Testing the DATABASE tool (real local SQLite query)")
print("=" * 60)
result = database_tool.run(
    "SELECT title, priority, assignee FROM tickets WHERE status='open' AND priority IN ('high','critical')"
)
print(result)

print()
print("=" * 60)
print("2. Testing the DB tool's write-guardrail (should be blocked)")
print("=" * 60)
print(database_tool.run("DROP TABLE tickets"))

print()
print("=" * 60)
print("3. Testing the GITHUB tool (real live API call, no key needed)")
print("=" * 60)
gh_result = github_tool.run("anthropics/anthropic-sdk-python", 1)
print(gh_result)

print()
print("=" * 60)
print("4. Simulating a full agent turn (fake LLM response, real tool)")
print("=" * 60)
trace = TraceLogger("How many critical tickets are open, and who owns them?")
trace.log("thought", text="I should check the database for open critical tickets.")
trace.log("tool_call", tool="query_tickets_db",
           input={"sql": "SELECT title, assignee FROM tickets WHERE status='open' AND priority='critical'"})
db_result = database_tool.run(
    "SELECT title, assignee FROM tickets WHERE status='open' AND priority='critical'"
)
trace.log("tool_result", tool="query_tickets_db", result=db_result)
trace.log("final_answer", text=f"(simulated) Found {db_result.get('row_count', 0)} open critical ticket(s).")
path = trace.save()

print()
print(f"Trace saved to: {path}")
print()
print("If you saw real rows above (not errors) and a saved trace path,")
print("the whole pipeline works. The only missing piece is real LLM")
print("reasoning, which needs a free GEMINI_API_KEY (aistudio.google.com/apikey).")
