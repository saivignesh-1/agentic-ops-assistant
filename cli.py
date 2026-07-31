"""
CLI entrypoint.

Usage:
    # get a free key at https://aistudio.google.com/apikey (no billing needed)
    export GEMINI_API_KEY=...            # macOS/Linux
    $env:GEMINI_API_KEY = "..."          # Windows PowerShell
    python db/init_db.py          # one-time: seed the sample database
    python cli.py                 # interactive mode
    python cli.py "your query"    # one-shot mode
"""
import os
import sys

from agent import run_agent


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
        print("  - 'Check the weather in Hyderabad, and if the critical tickets are")
        print("     unassigned, tell me who to escalate to.'")
        queries = iter(lambda: input("\n> "), "quit")

    for query in queries:
        if not query.strip():
            continue
        print(f"\n--- Trace for: {query!r} ---")
        answer, trace = run_agent(query)
        path = trace.save()
        print(f"\n=== Final Answer ===\n{answer}")
        print(f"(full trace saved to {path})")


if __name__ == "__main__":
    main()
