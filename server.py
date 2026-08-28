import json
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HTML_LAYOUT = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OpsAssistant Agent Center</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background-color: #0b0f19; color: #f3f4f6; font-family: system-ui, -apple-system, sans-serif; }
    .glass-panel { background: rgba(17, 24, 39, 0.75); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }
    .glow-purple { box-shadow: 0 0 20px rgba(99, 102, 241, 0.15); }
    .glow-amber { box-shadow: 0 0 25px rgba(245, 158, 11, 0.25); border-color: rgba(245, 158, 11, 0.4) !important; }
  </style>
</head>
<body class="min-h-screen p-6 flex flex-col justify-between">

  <!-- Header -->
  <header class="flex justify-between items-center mb-6 max-w-7xl mx-auto w-full">
    <div class="flex items-center space-x-3">
      <div class="w-10 h-10 rounded-xl bg-indigo-600/20 border border-indigo-500/40 flex items-center justify-center text-indigo-400 font-bold text-xl">
        ⚡
      </div>
      <div>
        <h1 class="text-xl font-bold bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">OpsAssistant Agent Center</h1>
        <p class="text-xs text-gray-400">FastAPI Engine • ReAct & HITL Security Guardrails Enabled</p>
      </div>
    </div>
    <div class="flex items-center space-x-2 bg-emerald-500/10 border border-emerald-500/30 px-3 py-1.5 rounded-full text-xs text-emerald-400 font-medium">
      <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
      <span>System Live</span>
    </div>
  </header>

  <!-- Main Grid -->
  <main class="grid grid-cols-1 lg:grid-cols-3 gap-6 max-w-7xl mx-auto w-full flex-grow">
    
    <!-- Left Column: Stream & Input -->
    <section class="lg:col-span-2 flex flex-col space-y-4">
      <div class="glass-panel rounded-2xl p-4 flex-grow flex flex-col h-[500px] glow-purple">
        <div class="flex justify-between items-center border-b border-gray-800 pb-3 mb-3">
          <span class="text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-2">
            📄 Live Agent Reasoning Stream
          </span>
          <span id="stream-status" class="text-xs text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20">Idle</span>
        </div>
        <div id="stream-output" class="flex-grow overflow-y-auto font-mono text-sm space-y-3 pr-2">
          <div class="p-2.5 rounded-lg bg-gray-900/60 border border-gray-800 text-gray-400">
            [SYSTEM]: Ready. Enter an operational prompt below to execute agent workflow.
          </div>
        </div>
      </div>

      <!-- Quick Actions & Input -->
      <div class="space-y-2">
        <div class="flex gap-2 text-xs">
          <button onclick="document.getElementById('user-input').value='Check weather in Tokyo'" class="px-3 py-1 rounded-full bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 transition">
            🌤️ Check Tokyo Weather
          </button>
          <button onclick="document.getElementById('user-input').value='Update ticket status for ticket 6 to closed'" class="px-3 py-1 rounded-full bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 transition">
            🎫 Close Ticket #6
          </button>
        </div>
        
        <div class="flex gap-2">
          <input id="user-input" type="text" placeholder="e.g., Update ticket status for ticket 6 to closed..." 
            class="flex-grow bg-gray-900/80 border border-gray-700 focus:border-indigo-500 rounded-xl px-4 py-3 text-sm focus:outline-none transition text-white">
          <button onclick="runAgent()" class="bg-indigo-600 hover:bg-indigo-500 text-white font-medium px-6 py-3 rounded-xl text-sm transition shadow-lg shadow-indigo-600/30">
            Run Agent
          </button>
        </div>
      </div>
    </section>

    <!-- Right Column: HITL Control Gate -->
    <section class="glass-panel rounded-2xl p-5 flex flex-col justify-between h-[580px] border-amber-500/20">
      <div>
        <div class="flex items-center space-x-2 text-amber-400 font-bold border-b border-gray-800 pb-3 mb-4">
          <span>⚠️</span>
          <span class="tracking-wide">HITL APPROVAL GATE</span>
        </div>
        
        <p class="text-xs text-gray-400 mb-4">Pending high-risk tool execution intercept:</p>

        <div id="hitl-box" class="glass-panel rounded-xl p-4 space-y-3">
          <div class="text-xs text-gray-400">Status: <span id="hitl-status" class="text-gray-200 font-mono">Idle</span></div>
          <div class="text-xs text-gray-400">Target: <span id="hitl-target" class="text-gray-200 font-mono">Waiting for execution</span></div>
          <div id="hitl-payload-container" class="hidden text-xs space-y-1">
            <span class="text-gray-400">Payload:</span>
            <pre id="hitl-payload" class="bg-gray-950 p-2.5 rounded-lg text-[11px] font-mono text-emerald-400 overflow-x-auto border border-gray-800"></pre>
          </div>
        </div>
      </div>

      <!-- HITL Buttons -->
      <div class="grid grid-cols-2 gap-3 pt-4 border-t border-gray-800">
        <button id="btn-approve" onclick="sendHITLResponse(true)" disabled class="bg-emerald-600/40 opacity-50 cursor-not-allowed text-white font-semibold py-3 rounded-xl text-sm transition">
          ✓ Approve
        </button>
        <button id="btn-reject" onclick="sendHITLResponse(false)" disabled class="bg-rose-600/40 opacity-50 cursor-not-allowed text-white font-semibold py-3 rounded-xl text-sm transition">
          ✕ Reject
        </button>
      </div>
    </section>

  </main>

  <script>
    let currentSessionId = null;

    async function runAgent() {
      const input = document.getElementById('user-input').value;
      if (!input) return;

      const streamOutput = document.getElementById('stream-output');
      streamOutput.innerHTML = '';
      
      const evtSource = new EventSource(`/run?prompt=${encodeURIComponent(input)}`);
      document.getElementById('stream-status').innerText = 'Streaming';

      evtSource.onmessage = function(e) {
        const data = JSON.parse(e.data);
        
        if (data.type === 'thought') {
          appendLog('THOUGHT', data.content, 'bg-purple-500/20 text-purple-300 border-purple-500/30');
        } else if (data.type === 'tool_call') {
          appendLog('TOOL EXECUTE', data.content, 'bg-blue-500/20 text-blue-300 border-blue-500/30');
        } else if (data.type === 'hitl_intercept') {
          appendLog('HITL INTERCEPT', data.content, 'bg-amber-500/20 text-amber-300 border-amber-500/30');
          activateHITLGate(data);
        } else if (data.type === 'final_answer') {
          appendLog('FINAL ANSWER', data.content, 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30');
          document.getElementById('stream-status').innerText = 'Completed';
          evtSource.close();
        }
      };
    }

    function appendLog(badge, text, badgeStyles) {
      const streamOutput = document.getElementById('stream-output');
      const div = document.createElement('div');
      div.className = 'p-2.5 rounded-lg bg-gray-900/60 border border-gray-800 text-gray-300';
      div.innerHTML = `<span class="text-xs font-bold px-2 py-0.5 rounded border ${badgeStyles} mr-2">${badge}</span><span>${text}</span>`;
      streamOutput.appendChild(div);
      streamOutput.scrollTop = streamOutput.scrollHeight;
    }

    function activateHITLGate(data) {
      document.getElementById('hitl-status').innerText = 'Action pending approval';
      document.getElementById('hitl-target').innerText = data.tool_name || 'update_ticket';
      document.getElementById('hitl-payload-container').classList.remove('hidden');
      document.getElementById('hitl-payload').innerText = JSON.stringify(data.payload || {}, null, 2);

      const btnApprove = document.getElementById('btn-approve');
      const btnReject = document.getElementById('btn-reject');

      btnApprove.disabled = false;
      btnApprove.className = 'bg-emerald-600 hover:bg-emerald-500 text-white font-semibold py-3 rounded-xl text-sm transition shadow-lg';

      btnReject.disabled = false;
      btnReject.className = 'bg-rose-600 hover:bg-rose-500 text-white font-semibold py-3 rounded-xl text-sm transition shadow-lg';
    }

    async function sendHITLResponse(approved) {
      await fetch('/hitl-response', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: approved })
      });

      document.getElementById('btn-approve').disabled = true;
      document.getElementById('btn-approve').className = 'bg-emerald-600/40 opacity-50 cursor-not-allowed text-white font-semibold py-3 rounded-xl text-sm transition';

      document.getElementById('btn-reject').disabled = true;
      document.getElementById('btn-reject').className = 'bg-rose-600/40 opacity-50 cursor-not-allowed text-white font-semibold py-3 rounded-xl text-sm transition';
      
      document.getElementById('hitl-status').innerText = approved ? 'Approved' : 'Rejected';
    }
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    return HTML_LAYOUT