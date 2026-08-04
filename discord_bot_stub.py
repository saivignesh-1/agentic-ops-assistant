"""
Discord integration stub.

This is intentionally the *only* extra code needed to expose the agent
in a Discord bot -- the agent, tools, and trace logger are unchanged.
Reasoning steps are posted as a collapsed-looking trace message before
the final answer, similar to how you'd surface "thinking" in a chat UI.

If the agent wants to run the one tool with real side effects
(update_ticket), it pauses and posts a confirmation message with ✅/❌
reactions -- the write only executes if the original requester reacts ✅
within 60 seconds. This is the same human-in-the-loop gate as the CLI,
just adapted to Discord's UI.

Requires: pip install discord.py
Env vars: DISCORD_BOT_TOKEN, GEMINI_API_KEY
"""
import asyncio
import os
import discord

from agent import run_agent, resume_agent, PendingAction

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

TRIGGER_PREFIX = "!agent "  # e.g. "!agent what's the status of issue #42 on owner/repo?"
CONFIRM_TIMEOUT_SECONDS = 60


def format_trace(trace) -> str:
    lines = []
    for s in trace.steps:
        if s["type"] == "tool_call":
            lines.append(f"🔧 calling `{s['tool']}` with `{s['input']}`")
        elif s["type"] == "tool_result":
            lines.append(f"↳ result: `{str(s['result'])[:200]}`")
        elif s["type"] == "thought":
            lines.append(f"💭 {s['text'][:200]}")
        elif s["type"] == "confirmation_required":
            lines.append(f"⏸️ paused for approval: `{s['tool']}({s['input']})`")
        elif s["type"] == "action_cancelled":
            lines.append(f"🚫 cancelled: `{s['tool']}({s['input']})`")
    return "\n".join(lines) if lines else "(no intermediate steps)"


async def confirm_via_reactions(message: discord.Message, author: discord.User, pending: PendingAction) -> bool:
    """Posts the proposed write action and waits for the requester to
    approve (✅) or reject (❌) via reaction. Returns False on timeout."""
    prompt = await message.channel.send(
        f"⚠️ **Confirmation needed** — I want to run:\n"
        f"`{pending.tool}({pending.input})`\n"
        f"React with ✅ to approve or ❌ to cancel ({CONFIRM_TIMEOUT_SECONDS}s)."
    )
    await prompt.add_reaction("✅")
    await prompt.add_reaction("❌")

    def check(reaction, user):
        return (
            user.id == author.id
            and reaction.message.id == prompt.id
            and str(reaction.emoji) in ("✅", "❌")
        )

    try:
        reaction, _ = await client.wait_for("reaction_add", timeout=CONFIRM_TIMEOUT_SECONDS, check=check)
        return str(reaction.emoji) == "✅"
    except asyncio.TimeoutError:
        await message.channel.send("⌛ No response in time — cancelling that action.")
        return False


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
        result, trace = await asyncio.to_thread(run_agent, query)

        # Keep resolving PendingActions (asking the human each time) until
        # the agent produces a plain final-answer string.
        while isinstance(result, PendingAction):
            approved = await confirm_via_reactions(message, message.author, result)
            result, trace = await asyncio.to_thread(resume_agent, result, approved, trace)

        trace.save()

    trace_text = format_trace(trace)
    if len(trace_text) > 1000:
        trace_text = trace_text[:1000] + "…"

    await message.reply(f"**Reasoning trace:**\n{trace_text}\n\n**Answer:**\n{result}")


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("Set DISCORD_BOT_TOKEN before running the bot.")
    client.run(token)
