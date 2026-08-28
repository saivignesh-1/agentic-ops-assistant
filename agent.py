"""
Core agent loop -- Enhanced with RBAC, Severity-based HITL, and dynamic context.
"""
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Set

from google import genai
from google.genai import types

# Import custom tool definitions and logger
from tools import github_tool, database_tool, weather_tool, ticket_write_tool
from trace_logger import TraceLogger

# Initialize Gemini Client with default key or environment variable fallback
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_KEY)

MODEL_CANDIDATES = [
    "gemini-3.6-flash",
    "gemini-2.5-flash",
]
MAX_TURNS = 8

class ActionSeverity(Enum):
    READ_ONLY = "read_only"
    MEDIUM = "medium"    # e.g., updates
    HIGH = "high"        # e.g., deletes, infrastructure changes

class UserRole(Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"

@dataclass
class UserContext:
    user_id: str
    role: UserRole = UserRole.OPERATOR

# Define action permissions and severities
TOOL_METADATA = {
    "get_github_issue": {"severity": ActionSeverity.READ_ONLY, "min_role": UserRole.VIEWER},
    "query_tickets_db": {"severity": ActionSeverity.READ_ONLY, "min_role": UserRole.VIEWER},
    "get_weather": {"severity": ActionSeverity.READ_ONLY, "min_role": UserRole.VIEWER},
    "update_ticket": {"severity": ActionSeverity.MEDIUM, "min_role": UserRole.OPERATOR},
}

SYSTEM_PROMPT = """You are an Operations Assistant with access to enterprise operational tools:
- get_github_issue: look up the live status of a GitHub issue/PR
- query_tickets_db: read-only SQL access to an internal support ticket database
- get_weather: current weather for a city
- update_ticket: change a ticket's status/assignee (requires human confirmation)

Always verify constraints before taking action. Rely on real tool data rather than assumptions.
"""

DISPATCH = {
    "get_github_issue": lambda args: github_tool.run(**args),
    "query_tickets_db": lambda args: database_tool.run(**args),
    "get_weather": lambda args: weather_tool.run(**args),
    "update_ticket": lambda args: ticket_write_tool.run(**args),
}

def _to_gemini_declaration(anthropic_schema: dict) -> dict:
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
    tool: str
    input: dict
    severity: ActionSeverity
    user_context: UserContext
    _contents: list
    _model: str
    _api_key: Optional[str]

def _requires_approval(tool_name: str, user_context: UserContext) -> bool:
    meta = TOOL_METADATA.get(tool_name, {"severity": ActionSeverity.HIGH})
    
    # Read-only actions never require approval
    if meta["severity"] == ActionSeverity.READ_ONLY:
        return False
        
    return True

def _call_model_with_fallback(client_instance, model, contents, trace):
    candidates_to_try = [model] if model else MODEL_CANDIDATES
    last_error = None
    for candidate_model in candidates_to_try:
        try:
            response = client_instance.models.generate_content(
                model=candidate_model, contents=contents, config=CONFIG
            )
            if model is None:
                trace.log("thought", text=f"(using model: {candidate_model})")
            return response, candidate_model
        except Exception as e:
            last_error = e
            if "404" in str(e) or "NOT_FOUND" in str(e) or "429" in str(e):
                continue
            break
    trace.log("error", message=f"Gemini API error: {last_error}")
    return None, None

def _run_turns(client_instance, model, contents, trace, api_key, user_context: UserContext, turns_used=0):
    for turn in range(turns_used, MAX_TURNS):
        response, model = _call_model_with_fallback(client_instance, model, contents, trace)
        if response is None:
            return "Agent failed due to an API error."

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

        # Check for tool execution permissions & HITL gates
        for fc in function_calls:
            meta = TOOL_METADATA.get(fc.name, {"severity": ActionSeverity.HIGH, "min_role": UserRole.ADMIN})
            
            # 1. RBAC check
            role_hierarchy = {UserRole.VIEWER: 1, UserRole.OPERATOR: 2, UserRole.ADMIN: 3}
            if role_hierarchy[user_context.role] < role_hierarchy[meta["min_role"]]:
                error_msg = f"Permission Denied: User role '{user_context.role.value}' cannot execute '{fc.name}'."
                trace.log("permission_denied", tool=fc.name, user=user_context.user_id)
                
                # Report permission error back to the model turn
                contents.append(types.Content(role="user", parts=[
                    types.Part.from_function_response(name=fc.name, response={"error": error_msg})
                ]))
                continue

            # 2. HITL Approval Check
            if _requires_approval(fc.name, user_context):
                args = dict(fc.args) if fc.args else {}
                trace.log("tool_call", tool=fc.name, input=args)
                trace.log("confirmation_required", tool=fc.name, input=args)
                return PendingAction(
                    tool=fc.name,
                    input=args,
                    severity=meta["severity"],
                    user_context=user_context,
                    _contents=contents,
                    _model=model,
                    _api_key=api_key,
                )

        # Execute read-only / auto-approved tools
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
                    result = {"error": f"Tool execution failed: {str(e)}"}
            
            trace.log("tool_result", tool=fc.name, result=result)
            response_parts.append(types.Part.from_function_response(name=fc.name, response=result))

        contents.append(types.Content(role="user", parts=response_parts))

    trace.log("error", message="Agent exceeded turn limit.")
    return "Agent hit the maximum iteration limit."

def run_agent(user_query: str, user_context: Optional[UserContext] = None, api_key: Optional[str] = None):
    if user_context is None:
        user_context = UserContext(user_id="default_user", role=UserRole.OPERATOR)
        
    client_instance = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY"))
    trace = TraceLogger(user_query)
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_query)])]
    result = _run_turns(client_instance, None, contents, trace, api_key, user_context)
    return result, trace

def resume_agent(pending: PendingAction, approved: bool, trace: TraceLogger):
    client_instance = genai.Client(api_key=pending._api_key or os.environ.get("GEMINI_API_KEY"))

    if approved:
        handler = DISPATCH.get(pending.tool)
        try:
            result_data = handler(pending.input)
        except Exception as e:
            result_data = {"error": f"Tool execution error: {e}"}
        trace.log("tool_result", tool=pending.tool, result=result_data)
    else:
        result_data = {"status": "cancelled_by_user", "message": "Action rejected by human operator."}
        trace.log("action_cancelled", tool=pending.tool, input=pending.input)

    pending._contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_function_response(name=pending.tool, response=result_data)],
        )
    )
    return _run_turns(client_instance, pending._model, pending._contents, trace, pending._api_key, pending.user_context)