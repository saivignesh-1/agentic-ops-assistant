"""
Core agent loop -- Gemini version, with human-in-the-loop confirmation.

This is a ReAct-style agent: on each turn the model either
  (a) requests a function_call -> we execute the real tool and feed the
      result back, or
  (b) emits a final text answer -> we stop.

One tool -- update_ticket -- has real side effects (it writes to the DB).
Tools in WRITE_TOOLS are never auto-executed: instead run_agent() pauses
and returns a PendingAction describing exactly what it wants to do. The
caller (cli.py / discord_bot_stub.py) shows that to a human and only
calls resume_agent(..., approved=True) if they confirm. This mirrors how
a real production agent should handle any action with side effects.

Every step (model reasoning text, tool call, tool result, confirmation
request, final answer) is written to a TraceLogger so the whole decision
process is visible, not just the final output.

Uses the free Gemini API (no billing required). Get a key at
https://aistudio.google.com/apikey and set it as GEMINI_API_KEY.
"""
import os
from dataclasses import dataclass
from google import genai
from google.genai import types

from tools import github_tool, database_tool, weather_tool, ticket_write_tool
from trace_logger import TraceLogger

# Google has been deprecating/retiring Gemini model names frequently in 2026
# (2.0-flash retired March 2026, 2.5-flash cut off for new users mid-2026, etc).
# Rather than hardcode one name that might 404 by the time you run this, try
# a list of candidates in order and use whichever one your account can access.
MODEL_CANDIDATES = [
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]
MAX_TURNS = 8  # hard cap so a confused agent can't loop forever

# Tools listed here are never auto-executed -- the agent always pauses for
# human confirmation first. Everything else (read-only tools) runs immediately.
WRITE_TOOLS = {"update_ticket"}

SYSTEM_PROMPT = """You are an operations assistant with access to real tools:
- get_github_issue: look up the live status of a GitHub issue/PR
- query_tickets_db: read-only SQL access to an internal support ticket database
- get_weather: current weather for a city
- update_ticket: change a ticket's status/assignee (this makes a REAL change
  and will always require human confirmation before it takes effect, so feel
  free to call it whenever the user asks to reassign/close/update a ticket --
  you don't need to ask permission yourself, the system handles that)

Use tools whenever the user's request needs real, current, or specific data —
don't guess or make up data a tool could answer. You may call multiple tools,
and chain them (e.g. use one tool's result to decide the next call), before
giving your final answer. Keep your final answer concise and directly useful.
"""

DISPATCH = {
    "get_github_issue": lambda args: github_tool.run(**args),
    "query_tickets_db": lambda args: database_tool.run(**args),
    "get_weather": lambda args: weather_tool.run(**args),
    "update_ticket": lambda args: ticket_write_tool.run(**args),
}


def _to_gemini_declaration(anthropic_schema: dict) -> dict:
    """Our tool modules define schemas in Anthropic's {name, description,
    input_schema} shape. Gemini expects {name, description, parameters} --
    same JSON-schema body, different key name. Convert here so tools/*.py
    doesn't need to know which LLM backend is in use."""
    return {
        "name": anthropic_schema["name"],
        "description": anthropic_schema["description"],
        "parameters": anthropic_schema["input_schema"],
    }


TOOLS = types.Tool(
    function_declarations=[
        _to_gemini_declaration(github_tool.TOOL_SCHEMA),
        _to_gemini_declaration(database_tool.TOOL_SCHEMA),
        _to_gemini_declaration(weather_tool.TOOL_SCHEMA),
        _to_gemini_declaration(ticket_write_tool.TOOL_SCHEMA),
    ]
)

CONFIG = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, tools=[TOOLS])


@dataclass
class PendingAction:
    """Returned instead of a final answer when the agent wants to run a
    write tool. Hold onto this and pass it to resume_agent() once a human
    has approved or rejected it."""
    tool: str
    input: dict
    _contents: list
    _model: str
    _api_key: str | None


def _call_model_with_fallback(client, model, contents, trace):
    """Try `model` if we already resolved one, else walk MODEL_CANDIDATES.
    Returns (response, resolved_model) or (None, None) on total failure."""
    candidates_to_try = [model] if model else MODEL_CANDIDATES
    last_error = None
    for candidate_model in candidates_to_try:
        try:
            response = client.models.generate_content(
                model=candidate_model, contents=contents, config=CONFIG
            )
            if model is None:
                trace.log("thought", text=f"(using model: {candidate_model})")
            return response, candidate_model
        except Exception as e:
            last_error = e
            if "404" in str(e) or "NOT_FOUND" in str(e) or "429" in str(e):
                continue  # this model is dead/exhausted -> try the next one
            break  # some other error (bad key, network) -> don't keep guessing
    trace.log("error", message=f"Gemini API error: {last_error}")
    return None, None


def _run_turns(client, model, contents, trace, api_key, turns_used=0):
    """Runs the agent loop starting from `contents`. Returns either a
    final answer (str) or a PendingAction if a write tool needs confirmation."""
    for turn in range(turns_used, MAX_TURNS):
        response, model = _call_model_with_fallback(client, model, contents, trace)
        if response is None:
            return f"Agent failed due to an API error."

        candidate = response.candidates[0]
        parts = candidate.content.parts or []
        function_calls = [p.function_call for p in parts if p.function_call]

        for p in parts:
            if getattr(p, "text", None) and p.text.strip():
                trace.log("thought", text=p.text.strip())

        if not function_calls:
            final_answer = (response.text or "").strip()
            trace.log("final_answer", text=final_answer)
            return final_answer

        contents.append(candidate.content)

        # If any requested call is a write tool, pause for confirmation before
        # executing ANYTHING else this turn (keeps the flow simple to reason about).
        write_call = next((fc for fc in function_calls if fc.name in WRITE_TOOLS), None)
        if write_call is not None:
            args = dict(write_call.args) if write_call.args else {}
            trace.log("tool_call", tool=write_call.name, input=args)
            trace.log("confirmation_required", tool=write_call.name, input=args)
            return PendingAction(
                tool=write_call.name, input=args,
                _contents=contents, _model=model, _api_key=api_key,
            )

        response_parts = []
        for fc in function_calls:
            args = dict(fc.args) if fc.args else {}
            trace.log("tool_call", tool=fc.name, input=args)
            handler = DISPATCH.get(fc.name)
            if handler is None:
                result = {"error": f"Unknown tool '{fc.name}'"}
            else:
                try:
                    result = handler(args)
                except Exception as e:
                    result = {"error": f"Tool raised an exception: {e}"}
            trace.log("tool_result", tool=fc.name, result=result)
            response_parts.append(types.Part.from_function_response(name=fc.name, response=result))

        contents.append(types.Content(role="user", parts=response_parts))

    trace.log("error", message="Agent hit the max-turn limit without reaching a final answer.")
    return "Agent hit the max-turn limit without reaching a final answer."


def run_agent(user_query: str, api_key: str | None = None):
    """Runs the agent loop for a single user query.
    Returns (result, trace) where result is either:
      - a str final answer, or
      - a PendingAction if a write tool needs human confirmation
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY"))
    trace = TraceLogger(user_query)
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_query)])]
    result = _run_turns(client, None, contents, trace, api_key)
    return result, trace


def resume_agent(pending: PendingAction, approved: bool, trace: TraceLogger):
    """Call after a human has approved/rejected a PendingAction. Executes
    (or skips) the write tool, feeds the result back to the model, and
    continues the loop. Returns (result, trace) with the same shape as run_agent."""
    client = genai.Client(api_key=pending._api_key or os.environ.get("GEMINI_API_KEY"))

    if approved:
        handler = DISPATCH.get(pending.tool)
        try:
            result_data = handler(pending.input)
        except Exception as e:
            result_data = {"error": f"Tool raised an exception: {e}"}
        trace.log("tool_result", tool=pending.tool, result=result_data)
    else:
        result_data = {"status": "cancelled_by_user"}
        trace.log("action_cancelled", tool=pending.tool, input=pending.input)

    pending._contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_function_response(name=pending.tool, response=result_data)],
        )
    )
    result = _run_turns(client, pending._model, pending._contents, trace, pending._api_key)
    return result, trace
