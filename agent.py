"""
Core agent loop -- Gemini version.

This is a ReAct-style agent: on each turn the model either
  (a) requests a function_call -> we execute the real tool and feed the
      result back, or
  (b) emits a final text answer -> we stop.

Every step (model reasoning text, tool call, tool result, final answer)
is written to a TraceLogger so the whole decision process is visible,
not just the final output.

Uses the free Gemini API (no billing required). Get a key at
https://aistudio.google.com/apikey and set it as GEMINI_API_KEY.
"""
import os
from google import genai
from google.genai import types

from tools import github_tool, database_tool, weather_tool
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

SYSTEM_PROMPT = """You are an operations assistant with access to real tools:
- get_github_issue: look up the live status of a GitHub issue/PR
- query_tickets_db: read-only SQL access to an internal support ticket database
- get_weather: current weather for a city

Use tools whenever the user's request needs real, current, or specific data —
don't guess or make up data a tool could answer. You may call multiple tools,
and chain them (e.g. use one tool's result to decide the next call), before
giving your final answer. Keep your final answer concise and directly useful.
"""

DISPATCH = {
    "get_github_issue": lambda args: github_tool.run(**args),
    "query_tickets_db": lambda args: database_tool.run(**args),
    "get_weather": lambda args: weather_tool.run(**args),
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
    ]
)


def run_agent(user_query: str, api_key: str | None = None) -> tuple[str, TraceLogger]:
    """Runs the agent loop for a single user query. Returns (final_answer, trace)."""
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY"))
    trace = TraceLogger(user_query)

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[TOOLS],
    )
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_query)])]

    final_answer = None
    model = None  # resolved on the first successful call, then reused

    for turn in range(MAX_TURNS):
        response = None
        candidates_to_try = [model] if model else MODEL_CANDIDATES
        last_error = None

        for candidate_model in candidates_to_try:
            try:
                response = client.models.generate_content(
                    model=candidate_model, contents=contents, config=config
                )
                if model is None:
                    model = candidate_model
                    trace.log("thought", text=f"(using model: {model})")
                break
            except Exception as e:
                last_error = e
                # Model unavailable (404) or over quota (429) -> try the next candidate
                if "404" in str(e) or "NOT_FOUND" in str(e) or "429" in str(e):
                    continue
                # Some other error (bad key, network, etc) -> don't keep guessing models
                break

        if response is None:
            trace.log("error", message=f"Gemini API error: {last_error}")
            return f"Agent failed due to an API error: {last_error}", trace

        candidate = response.candidates[0]
        parts = candidate.content.parts or []

        function_calls = [p.function_call for p in parts if p.function_call]

        # Log any reasoning text the model produced this turn
        for p in parts:
            if getattr(p, "text", None) and p.text.strip():
                trace.log("thought", text=p.text.strip())

        if not function_calls:
            final_answer = (response.text or "").strip()
            trace.log("final_answer", text=final_answer)
            break

        # Model's turn (including function_call parts) goes back into history
        contents.append(candidate.content)

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
                except Exception as e:  # tool crashed; feed the error back to the model
                    result = {"error": f"Tool raised an exception: {e}"}
            trace.log("tool_result", tool=fc.name, result=result)
            response_parts.append(
                types.Part.from_function_response(name=fc.name, response=result)
            )

        contents.append(types.Content(role="user", parts=response_parts))
    else:
        final_answer = "Agent hit the max-turn limit without reaching a final answer."
        trace.log("error", message=final_answer)

    return final_answer, trace
