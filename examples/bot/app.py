"""A tiny rule-based sample bot used by the conversat examples.

No API keys, no external services: it answers greetings, arithmetic, help
requests and (deliberately) a few things badly, so that a test suite can catch
the differences. It also serves a minimal browser chat UI for the ``web``
connector.

Run it::

    python examples/bot/app.py --port 8099
    open http://127.0.0.1:8099/

Endpoints:
    POST /chat            {"message": "...", "user": "..."} -> {"reply": "..."}
    WS   /ws/chat         frames: {"message": "..."}     -> frames: {"reply": "..."}
    GET  /                tiny chat UI for Playwright
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
from datetime import UTC, datetime

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

app = FastAPI(title="conversat sample bot", version="1.0.0")

SESSIONS: dict[str, list[str]] = {}
LATENCY_MS = 0.0

GREETINGS = ("hello", "hi", "hey", "yo", "good morning", "good evening", "howdy")
FAREWELLS = ("bye", "goodbye", "see you", "later")
THANKS = ("thanks", "thank you", "thx", "cheers")
HELP_WORDS = ("help", "what can you do", "capabilities", "options")
REFUND_WORDS = ("refund", "return policy", "money back", "cancel")
PRIVACY_WORDS = ("privacy", "gdpr", "data", "personal information")
AGENT_WORDS = ("human", "agent", "real person", "representative", "support")

HELP_TEXT = (
    "I can greet you, do arithmetic, remember your name and explain our refund policy."
)

CHAT_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8"><title>conversat sample bot</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem}
 #log{border:1px solid #ddd;border-radius:8px;height:24rem;overflow:auto;padding:1rem}
 .msg{margin:.4rem 0;padding:.5rem .75rem;border-radius:10px;max-width:80%}
 .user{background:#e0f2fe;margin-left:auto}
 .bot{background:#f3f4f6}
 form{display:flex;gap:.5rem;margin-top:1rem}
 input{flex:1;padding:.6rem;border:1px solid #ccc;border-radius:6px}
 button{padding:.6rem 1rem;border:0;border-radius:6px;background:#0ea5e9;color:#fff}
</style>
</head>
<body>
<h1>conversat sample bot</h1>
<div id="log"></div>
<form id="f">
  <input id="chat-input" autocomplete="off" placeholder="Say something..." />
  <button id="send" type="submit">Send</button>
</form>
<script>
const log = document.getElementById('log');
const form = document.getElementById('f');
const input = document.getElementById('chat-input');

function add(text, who) {
  const el = document.createElement('div');
  el.className = 'msg ' + who;
  el.setAttribute('data-conversat-msg', who);
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  add(text, 'user');
  input.value = '';
  const response = await fetch('/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message: text, user: 'browser'})
  });
  const data = await response.json();
  add(data.reply, 'bot');
});
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# the "brain"
# --------------------------------------------------------------------------- #
def _remember_name(message: str) -> str | None:
    match = re.search(r"(?:my name is|i am|i'm|call me)\s+([A-Za-z][\w'-]{1,30})", message, re.I)
    return match.group(1).rstrip(".!?,") if match else None


def _arithmetic(message: str) -> str | None:
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([+\-*/x])\s*(-?\d+(?:\.\d+)?)", message)
    if not match:
        return None
    left, operator, right = match.group(1), match.group(2), match.group(3)
    a, b = float(left), float(right)
    try:
        if operator == "+":
            value = a + b
        elif operator == "-":
            value = a - b
        elif operator == "*" or operator == "x":
            value = a * b
        elif operator == "/":
            value = a / b if b else 0.0
        else:  # pragma: no cover - regex restricts the operator
            return None
    except ZeroDivisionError:
        return "I cannot divide by zero."
    return str(int(value)) if value.is_integer() else str(round(value, 4))


def respond(message: str, history: list[str]) -> str:
    """Deterministic, slightly flaky on purpose: the reply depends on history."""
    text = message.strip()
    if not text:
        return "You said nothing at all. Could you rephrase that?"

    lowered = text.lower()

    name = _remember_name(text)
    if name:
        history.append(f"__name__={name}")
        return f"Nice to meet you, {name}! I will remember that."

    for entry in reversed(history):
        if entry.startswith("__name__="):
            known = entry.split("=", 1)[1]
            if re.search(r"\b(my name|who am i|remember me|what.*my name)\b", lowered):
                return f"Your name is {known}, as you told me earlier."
            break

    value = _arithmetic(text)
    if value is not None:
        return f"The answer is {value}."

    if any(word in lowered for word in AGENT_WORDS):
        # Intentionally imperfect: some suites assert this does *not* happen.
        return "I am a bot, but a human agent can take over during business hours."
    if any(word in lowered for word in REFUND_WORDS):
        return (
            "Refunds are available within 30 days of purchase. "
            "Would you like me to start a refund request?"
        )
    if any(word in lowered for word in PRIVACY_WORDS):
        return "We only store what we need to answer you, and never sell your data."
    if any(word in lowered for word in HELP_WORDS):
        return HELP_TEXT
    if any(word in lowered for word in THANKS):
        return "Happy to help!"
    if any(word in lowered for word in FAREWELLS):
        return "Goodbye! Come back any time."
    if any(lowered.startswith(word) or f" {word}" in lowered for word in GREETINGS):
        return random.choice(  # noqa: S311 - variety is the point of a sample bot
            ["Hello! How can I help you today?", "Hi there! What can I do for you?"]
        )

    return (
        "I did not quite get that. Could you rephrase it, or ask what I can do?"
    )


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return CHAT_PAGE


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": datetime.now(UTC).isoformat()}


@app.post("/chat")
async def chat(payload: dict) -> dict[str, str]:
    message = str(payload.get("message") or payload.get("text") or "")
    user = str(payload.get("user") or "anonymous")
    history = SESSIONS.setdefault(user, [])
    if LATENCY_MS:
        await asyncio.sleep(LATENCY_MS / 1000)
    reply = respond(message, history)
    history.append(message)
    return {"reply": reply, "user": user, "at": datetime.now(UTC).isoformat()}


@app.post("/reset")
async def reset(payload: dict | None = None) -> dict[str, str]:
    user = str((payload or {}).get("user") or "anonymous")
    SESSIONS.pop(user, None)
    return {"status": "reset", "user": user}


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #
@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    history: list[str] = []
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                frame = json.loads(raw)
                message = str(frame.get("message") or frame.get("text") or "")
            except json.JSONDecodeError:
                message = raw
            if message.lower() in {"quit", "bye"}:
                await websocket.send_text(json.dumps({"reply": "Goodbye!"}))
                break
            await websocket.send_text(json.dumps({"reply": respond(message, history)}))
            history.append(message)
    except Exception:  # noqa: BLE001 - client disconnects are normal
        return


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="Run the conversat sample bot")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument(
        "--latency-ms",
        type=float,
        default=0.0,
        help="Artificial latency, handy for exercising response_time_under",
    )
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    global LATENCY_MS  # noqa: PLW0603 - simple sample script
    LATENCY_MS = args.latency_ms

    import uvicorn

    print(f"sample bot on http://{args.host}:{args.port}  (chat UI at /)")
    print(f"  POST http://{args.host}:{args.port}/chat")
    print(f"  WS   ws://{args.host}:{args.port}/ws/chat")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
