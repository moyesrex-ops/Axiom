import threading
import time
from typing import Callable

import requests

from actions.system_capabilities import system_capabilities
from agent.task_queue import TaskPriority, get_queue
from core.runtime_config import load_runtime_config
from core.secret_config import get_secret
from memory.runtime_store import log_event, recent_task_runs


_BRIDGE_LOCK = threading.Lock()
_BRIDGE_THREAD: threading.Thread | None = None


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
            _send_message(chat_id, f"Task {task_id} finished.\n\n{result}")
            log_event("telegram", "task_finished", f"[{task_id}] {goal[:200]}")
        except Exception as send_error:
            log_event("telegram", "task_finish_send_failed", f"{task_id}: {send_error}")

    task_id = queue.submit(
        goal=goal,
        priority=TaskPriority.NORMAL,
        speak=None,
        on_complete=_on_complete,
    )
    ack = f"Queued task {task_id}.\n\nGoal: {goal[:300]}"
    _send_message(chat_id, ack, reply_to_message_id=reply_to_message_id)
    log_event("telegram", "task_queued", f"[{task_id}] {goal[:200]}")
    if log_func:
        log_func(f"Telegram queued task [{task_id}]")


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
                "Any plain message can also be queued if queue_plain_messages is enabled."
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

    if _telegram_config().get("queue_plain_messages", True):
        _queue_task(chat_id, text, reply_to_message_id, log_func)
        return

    _send_message(chat_id, "Use /help for available commands.", reply_to_message_id=reply_to_message_id)


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
