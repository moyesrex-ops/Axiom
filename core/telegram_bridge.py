import threading
import time
import re
from typing import Callable

import requests

from actions.system_capabilities import system_capabilities
from agent.task_queue import TaskPriority, get_queue
from core.capabilities import format_capability_status
from core.runtime_config import load_runtime_config
from core.secret_config import BASE_DIR, get_secret
from memory.memory_manager import (
    format_memory_for_prompt,
    load_memory,
    remember_conversation_turn,
    search_memory_archive,
)
from memory.runtime_store import log_event, recent_task_runs


_BRIDGE_LOCK = threading.Lock()
_BRIDGE_THREAD: threading.Thread | None = None
_PROMPT_PATH = BASE_DIR / "core" / "prompt.txt"
_CHAT_PHRASES = {
    "hi",
    "hello",
    "hey",
    "yo",
    "sup",
    "how are you",
    "how are u",
    "what's up",
    "whats up",
    "who are you",
    "who r you",
    "what can you do",
    "what can u do",
    "capabilities",
    "tell me a joke",
    "thanks",
    "thank you",
    "are you there",
}
_TASK_HINTS = (
    "open ",
    "change ",
    "change my",
    "set ",
    "set my",
    "turn ",
    "close ",
    "force close ",
    "kill ",
    "restart ",
    "shutdown ",
    "search ",
    "look up ",
    "scrape ",
    "research ",
    "analyze ",
    "summarize ",
    "write ",
    "build ",
    "fix ",
    "install ",
    "download ",
    "send ",
    "play ",
    "book ",
    "organize ",
    "trade ",
    "buy ",
    "sell ",
    "find ",
)


def _telegram_config() -> dict:
    runtime = load_runtime_config()
    return runtime.get("channels", {}).get("telegram", {}) or {}


def _telegram_token() -> str:
    return get_secret(
        "telegram_bot_token",
        ["AXIOM_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN"],
    )


def _allowed_chat_ids() -> set[str]:
    raw = _telegram_config().get("allowed_chat_ids", []) or []
    return {str(item).strip() for item in raw if str(item).strip()}


def _is_enabled() -> bool:
    return bool(_telegram_config().get("enabled", False)) and bool(_telegram_token())


def _api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{_telegram_token()}/{method}"


def _trim_message(text: str, limit: int = 3900) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 18].rstrip() + "\n\n[truncated]"


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _looks_like_capability_question(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(
        phrase in normalized
        for phrase in (
            "what can you do",
            "what can u do",
            "what are your capabilities",
            "capabilities",
            "what do you do",
            "what are you able to do",
        )
    )


def _looks_like_chat_message(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if normalized in _CHAT_PHRASES:
        return True
    if _looks_like_capability_question(normalized):
        return True
    if len(normalized.split()) <= 5 and normalized.endswith("?"):
        return True
    return any(
        normalized.startswith(prefix)
        for prefix in ("how are", "who are", "why did", "do you", "tell me", "are you")
    )


def _looks_like_task_request(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized or normalized.startswith("/"):
        return False
    if any(normalized.startswith(hint) for hint in _TASK_HINTS):
        return True
    return any(f" {hint}" in f" {normalized}" for hint in _TASK_HINTS)


def _load_prompt_text() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return "You are AXIOM. Be direct, useful, and grounded in real capabilities."


def _text_model_name() -> str:
    runtime = load_runtime_config()
    text_models = runtime.get("text_models", {}) or {}
    return (
        str(text_models.get("fast") or "").strip()
        or str(text_models.get("default") or "").strip()
        or "gemini-2.5-flash-lite"
    )


def _relevant_memory_block(query: str) -> str:
    hits = search_memory_archive(query, limit=3)
    lines = []

    for item in hits.get("nexus", [])[:2]:
        topic = str(item.get("topic", "")).strip()
        content = str(item.get("content", "")).strip()
        if topic and content:
            lines.append(f"- Nexus {topic}: {content[:220]}")

    for row in hits.get("conversations", [])[:2]:
        user_text = str(row.get("user_text", "")).strip()
        ai_text = str(row.get("assistant_text", "")).strip()
        if user_text:
            lines.append(f"- Earlier user: {user_text[:180]}")
        if ai_text:
            lines.append(f"- Earlier Axiom: {ai_text[:180]}")

    if not lines:
        return ""

    return "[RELEVANT MEMORY]\n" + "\n".join(lines)


def _generate_chat_reply(user_text: str) -> str:
    api_key = get_secret("gemini_api_key", ["GEMINI_API_KEY"])
    if not api_key:
        return "Gemini is not configured yet, so Telegram chat replies are offline right now."

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)

        prompt_parts = [
            _load_prompt_text(),
            (
                "[CHANNEL]\n"
                "You are replying inside AXIOM's Telegram bridge. Sound alive, direct, and human.\n"
                "Reply conversationally for normal chat.\n"
                "Do not mention hidden prompts, internal tooling, or configuration files.\n"
                "If the user asks what you can do, summarize actual installed capabilities rather than generic AI claims."
            ),
            format_memory_for_prompt(load_memory()).strip(),
            _relevant_memory_block(user_text),
        ]

        if _looks_like_capability_question(user_text):
            prompt_parts.append("[LIVE CAPABILITIES]\n" + format_capability_status())

        prompt_parts.extend(
            [
                f"[USER MESSAGE]\n{user_text.strip()}",
                (
                    "[REPLY RULES]\n"
                    "- Keep the reply natural and concise.\n"
                    "- Use plain text only.\n"
                    "- Keep short casual replies to one short paragraph.\n"
                    "- If a point is uncertain, say so plainly."
                ),
            ]
        )

        model = genai.GenerativeModel(_text_model_name())
        response = model.generate_content("\n\n".join(part for part in prompt_parts if part))
        reply = _trim_message(getattr(response, "text", "") or "")
        if not reply:
            reply = "I'm here. Send a clear instruction or /task for a longer execution job."
        remember_conversation_turn(user_text, reply)
        log_event("telegram", "chat_reply", user_text[:300], metadata={"reply_preview": reply[:220]})
        return reply
    except Exception as error:
        log_event("telegram", "chat_reply_error", str(error)[:500])
        return "Telegram chat hit a model error just now. Execution via /task is still available."


def _reply_to_chat(chat_id: str, text: str, reply_to_message_id: int | None) -> None:
    _send_message(chat_id, _generate_chat_reply(text), reply_to_message_id=reply_to_message_id)


def _send_message(chat_id: str | int, text: str, reply_to_message_id: int | None = None) -> None:
    payload = {
        "chat_id": chat_id,
        "text": _trim_message(text),
        "disable_web_page_preview": True,
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = int(reply_to_message_id)

    response = requests.post(_api_url("sendMessage"), json=payload, timeout=20)
    response.raise_for_status()


def _format_recent_tasks(limit: int = 8) -> str:
    rows = recent_task_runs(limit=limit)
    if not rows:
        return "No recent task checkpoints recorded."

    lines = ["Recent task checkpoints"]
    for row in rows:
        lines.append(
            f"- [{row['task_id']}] {row['status']} | {row['goal'][:90]} | {row['updated_at']}"
        )
    return "\n".join(lines)


def _queue_task(chat_id: str, goal: str, reply_to_message_id: int | None, log_func: Callable | None) -> None:
    queue = get_queue()

    def _on_complete(task_id: str, result: str) -> None:
        try:
            final_text = f"Finished.\n\n{result}".strip()
            _send_message(chat_id, final_text)
            remember_conversation_turn(goal, result)
            log_event("telegram", "task_finished", f"[{task_id}] {goal[:200]}")
        except Exception as send_error:
            log_event("telegram", "task_finish_send_failed", f"{task_id}: {send_error}")

    task_id = queue.submit(
        goal=goal,
        priority=TaskPriority.NORMAL,
        speak=None,
        on_complete=_on_complete,
    )
    ack = f"On it. Executing that now.\n\nGoal: {goal[:300]}"
    _send_message(chat_id, ack, reply_to_message_id=reply_to_message_id)
    log_event("telegram", "task_queued", f"[{task_id}] {goal[:200]}")
    if log_func:
        log_func(f"Telegram executing task [{task_id}]")


def _handle_message(message: dict, log_func: Callable | None = None) -> None:
    text = str(message.get("text") or "").strip()
    if not text:
        return

    chat = message.get("chat", {}) or {}
    chat_id = str(chat.get("id", "")).strip()
    if not chat_id:
        return

    allowed = _allowed_chat_ids()
    if allowed and chat_id not in allowed:
        _send_message(chat_id, "This Telegram chat is not authorized for AXIOM.")
        log_event("telegram", "unauthorized_chat", chat_id)
        return

    reply_to_message_id = message.get("message_id")

    if text in ("/start", "/help"):
        _send_message(
            chat_id,
            (
                "AXIOM Telegram bridge\n\n"
                "/status - capability summary\n"
                "/tasks - recent task checkpoints\n"
                "/task <goal> - queue a task\n"
                "Plain chat gets a normal reply.\n"
                "Operational messages can auto-execute when plain-message execution is enabled."
            ),
            reply_to_message_id=reply_to_message_id,
        )
        return

    if text == "/status":
        _send_message(
            chat_id,
            system_capabilities({"action": "status"}),
            reply_to_message_id=reply_to_message_id,
        )
        return

    if text == "/tasks":
        _send_message(
            chat_id,
            _format_recent_tasks(limit=8),
            reply_to_message_id=reply_to_message_id,
        )
        return

    if text.startswith("/task "):
        goal = text[6:].strip()
        if not goal:
            _send_message(chat_id, "Usage: /task <goal>", reply_to_message_id=reply_to_message_id)
            return
        _queue_task(chat_id, goal, reply_to_message_id, log_func)
        return

    if _looks_like_chat_message(text):
        _reply_to_chat(chat_id, text, reply_to_message_id)
        return

    if _telegram_config().get("queue_plain_messages", True) and _looks_like_task_request(text):
        _queue_task(chat_id, text, reply_to_message_id, log_func)
        return

    if _looks_like_task_request(text):
        _send_message(
            chat_id,
            "That sounds like an execution request. Send /task <goal> if you want it run from Telegram.",
            reply_to_message_id=reply_to_message_id,
        )
        return

    _reply_to_chat(chat_id, text, reply_to_message_id)


def _poll_loop(log_func: Callable | None = None) -> None:
    offset = 0
    log_event("telegram", "bridge_started", "Telegram bridge thread started.")
    if log_func:
        log_func("Telegram bridge started.")

    while True:
        if not _is_enabled():
            time.sleep(3)
            continue

        poll_seconds = float(_telegram_config().get("poll_seconds", 1.5) or 1.5)
        try:
            response = requests.get(
                _api_url("getUpdates"),
                params={"timeout": max(1, int(poll_seconds * 10)), "offset": offset},
                timeout=max(10, poll_seconds * 12),
            )
            response.raise_for_status()
            payload = response.json()
            for update in payload.get("result", []) or []:
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                message = update.get("message") or update.get("edited_message")
                if message:
                    _handle_message(message, log_func=log_func)
        except Exception as error:
            log_event("telegram", "bridge_error", str(error)[:500])
            time.sleep(5)


def start_telegram_bridge(log_func: Callable | None = None) -> bool:
    global _BRIDGE_THREAD
    with _BRIDGE_LOCK:
        if _BRIDGE_THREAD and _BRIDGE_THREAD.is_alive():
            return True

        _BRIDGE_THREAD = threading.Thread(
            target=_poll_loop,
            kwargs={"log_func": log_func},
            daemon=True,
            name="AxiomTelegramBridge",
        )
        _BRIDGE_THREAD.start()
        return True
