"""
TraceLogger: records every step of the agent's reasoning loop
(model thoughts, tool calls, tool results, final answer) so the
whole decision process is auditable, not just the final output.
"""
import json
import os
from datetime import datetime, timezone


class TraceLogger:
    def __init__(self, query: str):
        self.query = query
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.steps = []

    def log(self, step_type: str, **data):
        """step_type: 'thought' | 'tool_call' | 'tool_result' | 'final_answer' | 'error'"""
        entry = {
            "step": len(self.steps) + 1,
            "type": step_type,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **data,
        }
        self.steps.append(entry)
        self._print_step(entry)
        return entry

    def get_logs(self):
        """Returns the list of recorded step entries for the FastAPI server/dashboard."""
        return self.steps

    def _print_step(self, entry):
        step, step_type = entry["step"], entry["type"]
        prefix = f"[{step:02d}] {step_type.upper():12s}"
        if step_type == "thought":
            print(f"{prefix} {entry.get('text', '')[:300]}")
        elif step_type == "tool_call":
            print(f"{prefix} {entry.get('tool', '')}({json.dumps(entry.get('input', {}))})")
        elif step_type == "tool_result":
            preview = json.dumps(entry.get("result", {}))[:300]
            print(f"{prefix} -> {preview}")
        elif step_type == "final_answer":
            print(f"{prefix} {entry.get('text', '')[:300]}")
        elif step_type == "error":
            print(f"{prefix} {entry.get('message', '')}")
        elif step_type == "confirmation_required":
            print(f"{prefix} {entry.get('tool', '')}({json.dumps(entry.get('input', {}))}) -- awaiting human approval")
        elif step_type == "action_cancelled":
            print(f"{prefix} {entry.get('tool', '')}({json.dumps(entry.get('input', {}))}) -- cancelled by user")
        else:
            print(f"{prefix} {json.dumps(entry)}")

    def save(self, directory="logs"):
        os.makedirs(directory, exist_ok=True)
        fname = f"trace_{self.started_at.replace(':', '-')}.json"
        path = os.path.join(directory, fname)
        with open(path, "w") as f:
            json.dump(
                {"query": self.query, "started_at": self.started_at, "steps": self.steps},
                f,
                indent=2,
            )
        return path
    
    def save(self):
        """Saves the logged steps to a JSON file in the logs directory."""
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        filename = f"trace_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(log_dir, filename)
        
        output = {
            "query": self.query,
            "started_at": self.started_at,
            "steps": self.steps
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
            
        return filepath