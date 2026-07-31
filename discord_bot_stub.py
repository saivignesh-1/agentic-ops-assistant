"""
Discord integration stub.

This is intentionally the *only* extra code needed to expose the agent
in a Discord bot -- the agent, tools, and trace logger are unchanged.
Reasoning steps are posted as a collapsed-looking trace message before
the final answer, similar to how you'd surface "thinking" in a chat UI.

Requires: pip install discord.py
Env vars: DISCORD_BOT_TOKEN, GEMINI_API_KEY
"""
import os
import discord

from agent import run_agent

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

TRIGGER_PREFIX = "!agent "  # e.g. "!agent what's the status of issue #42 on owner/repo?"


def format_trace(trace) -> str:
    lines = []
    for s in trace.steps:
        if s["type"] == "tool_call":
            lines.append(f"🔧 calling `{s['tool']}` with `{s['input']}`")
        elif s["type"] == "tool_result":
            lines.append(f"↳ result: `{str(s['result'])[:200]}`")
        elif s["type"] == "thought":
            lines.append(f"💭 {s['text'][:200]}")
    return "\n".join(lines) if lines else "(no intermediate steps)"


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not message.content.startswith(TRIGGER_PREFIX):
        return

    query = message.content[len(TRIGGER_PREFIX):].strip()
    async with message.channel.typing():
        answer, trace = run_agent(query)
        trace.save()

    trace_text = format_trace(trace)
    if len(trace_text) > 1000:
        trace_text = trace_text[:1000] + "…"

    await message.reply(f"**Reasoning trace:**\n{trace_text}\n\n**Answer:**\n{answer}")


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("Set DISCORD_BOT_TOKEN before running the bot.")
    client.run(token)
