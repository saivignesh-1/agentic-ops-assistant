"""
CLI entrypoint.

Usage:
    # get a free key at https://aistudio.google.com/apikey (no billing needed)
    export GEMINI_API_KEY=...            # macOS/Linux
    $env:GEMINI_API_KEY = "..."          # Windows PowerShell
    python db/init_db.py          # one-time: seed the sample database
    python cli.py                 # interactive mode
    python cli.py "your query"    # one-shot mode

Some requests (e.g. "reassign ticket #3 to sam") make the agent pause and
ask YOU to confirm before it writes anything -- that's the human-in-the-loop
gate for the one tool with real side effects (update_ticket).
"""
import os
import sys

from agent import run_agent, resume_agent, PendingAction


def handle_result(result, trace):
    """Keeps resolving PendingActions (asking the human each time) until
    the agent produces a plain final-answer string."""
    while isinstance(result, PendingAction):
        print(f"\n⚠️  The agent wants to run: {result.tool}({result.input})")
        choice = input("   Approve this action? [y/N] ").strip().lower()
        approved = choice in ("y", "yes")
        result, trace = resume_agent(result, approved=approved, trace=trace)
    return result, trace


def main():
    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: set the GEMINI_API_KEY environment variable first.")
        print("Get a free key (no billing required) at https://aistudio.google.com/apikey")
        sys.exit(1)

    if len(sys.argv) > 1:
        queries = [" ".join(sys.argv[1:])]
    else:
        print("Agentic assistant. Type a request, or 'quit' to exit.")
        print("Examples:")
        print("  - 'What's the status of issue #100 on anthropics/anthropic-sdk-python?'")
        print("  - 'How many critical or high priority tickets are still open?'")
        print("  - 'Reassign ticket #3 to sam and mark it in_progress' (asks for confirmation)")
        queries = iter(lambda: input("\n> "), "quit")

    for query in queries:
        if not query.strip():
            continue
        print(f"\n--- Trace for: {query!r} ---")
        result, trace = run_agent(query)
        answer, trace = handle_result(result, trace)
        path = trace.save()
        print(f"\n=== Final Answer ===\n{answer}")
        print(f"(full trace saved to {path})")


if __name__ == "__main__":
    main()
