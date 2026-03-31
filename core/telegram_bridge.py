import threading
import time
import re
import difflib
import json
from typing import Callable

import requests

from core import gemini_native as gn
from actions.system_capabilities import system_capabilities
from actions.trade_daemon_control import trade_daemon_control
from agent.task_queue import TaskPriority, get_queue
from core.capabilities import format_capability_status
from core.intelligence_router import route_message_kind
from core.runtime_config import load_runtime_config
from core.task_channels import submit_channel_task
from core.task_journal import format_task_snapshot
from core.secret_config import BASE_DIR, get_secret
from memory.memory_manager import (
    format_memory_for_prompt,
    load_memory,
    remember_conversation_turn,
    search_memory_archive,
)
from memory.runtime_store import get_channel_state, log_event, recent_task_runs, upsert_channel_state


_BRIDGE_LOCK = threading.Lock()
_BRIDGE_THREAD: threading.Thread | None = None
_STOP_EVENT = threading.Event()
_PROMPT_PATH = BASE_DIR / "core" / "prompt.txt"
_ACTIVE_CHAT_TASKS: dict[str, str] = {}
_LAST_CHAT_TASK_RESULTS: dict[str, dict] = {}
_COLOR_HINTS = (
    "red",
    "green",
    "blue",
    "white",
    "yellow",
    "orange",
    "purple",
    "pink",
    "cyan",
    "off",
    "rainbow",
    "glowing",
)
_COLOR_ALIASES = {
    "grain": "green",
    "gren": "green",
    "greeen": "green",
    "blu": "blue",
    "bleu": "blue",
    "reed": "red",
}
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
    "smooth thanks",
    "ok thanks",
    "okay thanks",
    "thanks axiom",
    "thank you axiom",
    "nice thanks",
    "cool thanks",
    "awesome thanks",
    "perfect thanks",
    "got it thanks",
    "are you there",
}
_TASK_HINTS = (
    "open ",
    "run ",
    "use ",
    "create ",
    "make ",
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
    "deploy ",
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
_EXPLICIT_TOOL_NAMES = {
    "gemini_native",
    "web_search",
    "browser_control",
    "file_controller",
    "cmd_control",
    "computer_use",
    "computer_control",
    "computer_settings",
    "code_helper",
    "codex_builder",
    "system_capabilities",
    "memory_archive",
    "skill_library",
    "agent_library",
    "tradingagents_control",
    "crucix_control",
    "lightpanda_control",
    "deerflow_control",
    "autoresearch_control",
}
_PLAIN_MESSAGE_MODES = {"operator", "smart", "legacy", "chat_only"}
_PROGRESS_FEEDBACK_TOPICS = {
    "executor_started",
    "direct_route_selected",
    "step_started",
    "step_retrying",
    "step_failed",
    "task_failed",
    "task_cancelled",
}
_CAPABILITY_TOKENS = (
    "lightpanda",
    "tradingagents",
    "mt5",
    "telegram",
    "mirofish",
    "automaton",
    "skill",
    "skills",
    "agent",
    "agents",
    "paperclip",
    "openfang",
    "symphony",
    "lossless",
    "deerflow",
    "crucix",
    "dexter",
    "pentagi",
    "autoresearch",
    "codex",
    "gemini",
)
_CAPABILITY_FRAMES = (
    "can you",
    "can u",
    "do you",
    "do u",
    "are you",
    "have you",
    "how do you",
    "what is",
    "what's",
    "whats",
    "know how to",
    "able to",
    "access",
    "have access",
    "work with",
    "familiar with",
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


def _chat_is_authorized(chat_id: str) -> bool:
    allowed = _allowed_chat_ids()
    if not allowed:
        return True
    return chat_id in allowed


def _chat_can_execute(chat_id: str) -> bool:
    allowed = _allowed_chat_ids()
    return bool(allowed) and chat_id in allowed


def _is_enabled() -> bool:
    return bool(_telegram_config().get("enabled", False)) and bool(_telegram_token())


def _plain_message_mode() -> str:
    mode = str(_telegram_config().get("plain_message_mode", "operator") or "operator").strip().lower()
    return mode if mode in _PLAIN_MESSAGE_MODES else "operator"


def _show_task_ids_in_messages() -> bool:
    return bool(_telegram_config().get("show_task_ids_in_messages", False))


def _telegram_feedback_settings() -> dict:
    cfg = _telegram_config()
    return {
        "speak_updates_enabled": bool(cfg.get("speak_updates_enabled", True)),
        "progress_updates_enabled": bool(cfg.get("progress_updates_enabled", True)),
        "speak_min_interval_seconds": max(0.0, float(cfg.get("speak_min_interval_seconds", 2.0) or 2.0)),
        "progress_min_interval_seconds": max(0.0, float(cfg.get("progress_min_interval_seconds", 4.0) or 4.0)),
        "max_feedback_messages_per_task": max(1, int(cfg.get("max_feedback_messages_per_task", 10) or 10)),
    }


def _api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{_telegram_token()}/{method}"


def _channel_state(chat_id: str) -> dict:
    shared = get_channel_state("operator", "shared")
    specific = get_channel_state("telegram", str(chat_id or "").strip())
    if not shared:
        return specific
    if not specific:
        return shared
    merged = dict(shared)
    merged.update({key: value for key, value in specific.items() if value not in (None, "", {}, [])})
    return merged


def _persist_channel_state(
    chat_id: str,
    *,
    active_task_id: str | None = None,
    last_task_id: str | None = None,
    last_goal: str | None = None,
    last_result: str | None = None,
    last_user_text: str | None = None,
    last_assistant_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    upsert_channel_state(
        channel="telegram",
        scope=str(chat_id or "").strip(),
        active_task_id=active_task_id,
        last_task_id=last_task_id,
        last_goal=last_goal,
        last_result=last_result,
        last_user_text=last_user_text,
        last_assistant_text=last_assistant_text,
        metadata=metadata,
    )


def _trim_message(text: str, limit: int = 3900) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 18].rstrip() + "\n\n[truncated]"


def _task_feedback_state() -> dict:
    return {
        "messages_sent": 0,
        "limit_notice_sent": False,
        "last_text": "",
        "last_sent_at": 0.0,
        "last_progress_at": 0.0,
        "last_speak_at": 0.0,
    }


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _looks_like_capability_question(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(
        phrase in normalized
        for phrase in (
            "what can you do",
            "what can u do",
            "what are your capabilities",
            "capabilities",
            "what do you do",
            "what are you able to do",
            "can you access",
            "can u access",
            "can you deploy",
            "can u deploy",
            "do you have access",
            "do u have access",
            "do you know how to use",
            "do u know how to use",
            "do you know how to work with",
            "do u know how to work with",
            "are you familiar with",
            "have you used",
        )
    ) or (
        any(token in normalized for token in _CAPABILITY_TOKENS)
        and any(frame in normalized for frame in _CAPABILITY_FRAMES)
        and (
            normalized.endswith("?")
            or normalized.startswith(("can ", "do ", "are ", "have ", "how ", "what "))
        )
    )


def _looks_like_runtime_status_question(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(
        phrase in normalized
        for phrase in (
            "what's happening",
            "whats happening",
            "what are you doing",
            "what r you doing",
            "status",
            "still working",
            "how's it going",
            "hows it going",
        )
    )


def _looks_like_task_followup(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(
        phrase in normalized
        for phrase in (
            "where is it",
            "where is the",
            "where's the",
            "done yet",
            "is it done",
            "finished yet",
            "link",
            "open it",
            "open the",
            "browser",
            "still working",
            "how much longer",
            "i'm waiting",
            "im waiting",
            "okay?",
        )
    )


def _looks_like_chat_message(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if normalized in _CHAT_PHRASES:
        return True
    if any(token in normalized for token in ("thank", "thanks", "appreciate", "good job", "nice one")):
        return True
    if _looks_like_capability_question(normalized):
        return True
    if len(normalized.split()) <= 5 and normalized.endswith("?"):
        return True
    if len(normalized.split()) <= 4 and any(
        token in normalized
        for token in ("cool", "smooth", "nice", "awesome", "perfect", "got it", "all good")
    ):
        return True
    return any(
        normalized.startswith(prefix)
        for prefix in ("how are", "who are", "why did", "do you", "tell me", "are you")
    )


def _looks_like_task_request(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized or normalized.startswith("/"):
        return False
    if _looks_like_explicit_tool_instruction(normalized):
        return True
    if any(normalized.startswith(hint) for hint in _TASK_HINTS):
        return True
    return any(f" {hint}" in f" {normalized}" for hint in _TASK_HINTS)


def _looks_like_explicit_tool_instruction(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized.startswith("use "):
        return False
    target = normalized[4:].split(" ", 1)[0].strip(".,:;!?")
    return target in _EXPLICIT_TOOL_NAMES or "_" in target


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
        or "gemini-3.1-flash-lite-preview"
    )


def _probe_bridge_state() -> dict:
    details: dict = {}

    try:
        response = requests.get(_api_url("getMe"), timeout=15)
        response.raise_for_status()
        result = (response.json() or {}).get("result", {}) or {}
        details["bot_id"] = result.get("id")
        details["bot_username"] = result.get("username", "")
        details["bot_name"] = result.get("first_name", "")
    except Exception as error:
        details["bot_probe_error"] = str(error)

    try:
        response = requests.get(_api_url("getWebhookInfo"), timeout=15)
        response.raise_for_status()
        result = (response.json() or {}).get("result", {}) or {}
        details["webhook_url"] = result.get("url", "")
        details["pending_update_count"] = int(result.get("pending_update_count", 0) or 0)
        last_error = str(result.get("last_error_message", "") or "").strip()
        if last_error:
            details["webhook_last_error"] = last_error
    except Exception as error:
        details["webhook_probe_error"] = str(error)

    return details


def _relevant_memory_block(query: str) -> str:
    hits = search_memory_archive(query, limit=3)
    lines = []

    for item in hits.get("knowledge", [])[:2]:
        topic = str(item.get("topic", "") or item.get("title", "")).strip()
        content = str(item.get("content", "")).strip()
        if topic and content:
            lines.append(f"- Memory {topic}: {content[:220]}")

    for row in hits.get("conversations", [])[:2]:
        user_text = str(row.get("user_text", "")).strip()
        ai_text = str(row.get("assistant_text", "")).strip()
        if user_text:
            lines.append(f"- Earlier user: {user_text[:180]}")
        if ai_text:
            lines.append(f"- Earlier Axiom: {ai_text[:180]}")

    for row in hits.get("graph", [])[:2]:
        source = str(row.get("source_name", "")).strip()
        relation = str(row.get("relation", "")).strip().replace("_", " ")
        target = str(row.get("target_name", "")).strip()
        if source and relation and target:
            lines.append(f"- Graph memory: {source} -> {relation} -> {target}")

    if not lines:
        return ""

    return "[RELEVANT MEMORY]\n" + "\n".join(lines)


def _active_task_snapshot(chat_id: str) -> dict | None:
    chat_id = str(chat_id or "").strip()
    task_id = _ACTIVE_CHAT_TASKS.get(chat_id)
    if not task_id:
        state = _channel_state(chat_id)
        task_id = str(state.get("active_task_id", "") or "").strip()
        if task_id:
            _ACTIVE_CHAT_TASKS[chat_id] = task_id
    if not task_id:
        return None
    status = get_queue().get_status(task_id)
    if not status or status.get("status") not in ("pending", "running"):
        _ACTIVE_CHAT_TASKS.pop(chat_id, None)
        _persist_channel_state(chat_id, active_task_id="")
        return None
    return status


def _format_active_task_status(chat_id: str) -> str:
    status = _active_task_snapshot(chat_id)
    if not status:
        return "No active Telegram task is running for this chat right now."
    snapshot = format_task_snapshot(str(status.get("task_id", "") or ""))
    if snapshot.startswith("Task ["):
        return snapshot.replace("Task [", "Active task [", 1)
    return snapshot


def _last_task_result(chat_id: str) -> dict:
    chat_id = str(chat_id or "").strip()
    cached = _LAST_CHAT_TASK_RESULTS.get(chat_id) or {}
    if cached:
        return cached

    state = _channel_state(chat_id)
    task_id = str(state.get("last_task_id", "") or "").strip()
    if not task_id:
        return {}
    result = {
        "task_id": task_id,
        "goal": str(state.get("last_goal", "") or "").strip(),
        "result": str(state.get("last_result", "") or "").strip(),
    }
    _LAST_CHAT_TASK_RESULTS[chat_id] = result
    return result


def _render_task_completion_message(result: str) -> str:
    text = str(result or "").strip()
    if not text:
        return "Done."
    return text


def _task_ack_message(goal: str, task_id: str, explicit: bool = False) -> str:
    normalized = _normalize_text(goal)
    if explicit:
        if _show_task_ids_in_messages():
            return f"Queued it.\n\nTask ID: {task_id}\nGoal: {goal[:300]}".strip()
        return f"Queued it.\n\nGoal: {goal[:300]}\n\nI'll report back here.".strip()
    if any(term in normalized for term in ("keyboard", "lighting", "backlight", "rgb", "lights")):
        base = "Changing that now."
    elif normalized.startswith(("open ", "launch ", "start ")):
        base = "Opening that now."
    elif normalized.startswith(("close ", "kill ", "restart ", "shutdown ")):
        base = "Handling that now."
    elif normalized.startswith(("search ", "look up ", "research ", "analyze ", "summarize ")):
        base = "Running that now."
    elif normalized.startswith(("create ", "build ", "make ", "write ", "deploy ", "fix ")):
        base = "Working on that now."
    else:
        base = "On it."
    if _show_task_ids_in_messages():
        return f"{base}\n\nTask ID: {task_id}\nI'll keep you posted here.".strip()
    return f"{base}\n\nI'll keep you posted here.".strip()


def _format_progress_feedback(event: dict | None) -> str:
    payload = dict(event or {})
    topic = str(payload.get("topic", "") or "").strip().lower()
    if topic and topic not in _PROGRESS_FEEDBACK_TOPICS:
        return ""

    message = str(payload.get("message", "") or "").strip()
    tool = str(payload.get("tool", "") or "").strip()
    description = str(payload.get("description", "") or "").strip()
    step_index = payload.get("step_index")
    step_total = payload.get("step_total")

    step_prefix = ""
    if step_index not in (None, ""):
        try:
            step_prefix = f"Step {int(step_index)}"
        except Exception:
            step_prefix = "Step"
        if step_total not in (None, ""):
            try:
                step_prefix += f"/{int(step_total)}"
            except Exception:
                pass

    if topic in {"executor_started", "direct_route_selected"}:
        return ""
    if step_prefix and tool and description:
        return f"{step_prefix}: {description[:220]}".strip()
    if step_prefix and message:
        lowered = message.lower()
        if lowered in {"step execution started.", "execution started."}:
            return ""
        return f"{step_prefix}: {message[:300]}".strip()
    if topic in {"task_failed", "task_cancelled"} and message:
        return message[:320]
    return message[:320] if message else ""


def _emit_task_feedback(
    chat_id: str,
    *,
    task_id: str,
    text: str,
    kind: str,
    state: dict,
    reply_to_message_id: int | None = None,
) -> None:
    message = _trim_message(text)
    if not message:
        return

    settings = _telegram_feedback_settings()
    enabled = bool(settings.get(f"{kind}_updates_enabled", False))
    if not enabled:
        return

    if message == str(state.get("last_text", "") or ""):
        return

    now = time.time()
    min_interval = float(settings.get(f"{kind}_min_interval_seconds", 0.0) or 0.0)
    last_kind_at = float(state.get(f"last_{kind}_at", 0.0) or 0.0)
    last_any_at = float(state.get("last_sent_at", 0.0) or 0.0)
    if (now - last_kind_at) < min_interval or (now - last_any_at) < 0.75:
        return

    max_messages = int(settings.get("max_feedback_messages_per_task", 10) or 10)
    if int(state.get("messages_sent", 0) or 0) >= max_messages:
        if not state.get("limit_notice_sent"):
            try:
                _send_message(
                    chat_id,
                    "Still running. Ask for status any time and I will report the latest checkpoint.",
                    reply_to_message_id=reply_to_message_id,
                )
                state["limit_notice_sent"] = True
            except Exception as error:
                log_event(
                    "telegram",
                    "task_feedback_send_failed",
                    str(error)[:500],
                    metadata={"chat_id": chat_id, "task_id": task_id, "kind": kind, "phase": "limit_notice"},
                )
        return

    try:
        _send_message(chat_id, message, reply_to_message_id=reply_to_message_id)
    except Exception as error:
        log_event(
            "telegram",
            "task_feedback_send_failed",
            str(error)[:500],
            metadata={"chat_id": chat_id, "task_id": task_id, "kind": kind},
        )
        return

    state["messages_sent"] = int(state.get("messages_sent", 0) or 0) + 1
    state["last_text"] = message
    state["last_sent_at"] = now
    state[f"last_{kind}_at"] = now
    _persist_channel_state(
        chat_id,
        active_task_id=task_id,
        last_assistant_text=message,
        metadata={"last_interaction": f"task_{kind}", "task_id": task_id},
    )


def _build_task_feedback_callbacks(
    chat_id: str,
    *,
    reply_to_message_id: int | None,
) -> tuple[Callable[[str], None], Callable[[str, dict | None], None]]:
    state = _task_feedback_state()

    def _speak_callback(text: str) -> None:
        _emit_task_feedback(
            chat_id,
            task_id=str(_ACTIVE_CHAT_TASKS.get(chat_id, "") or ""),
            text=str(text or ""),
            kind="speak",
            state=state,
            reply_to_message_id=reply_to_message_id,
        )

    def _progress_callback(task_id: str, event: dict | None) -> None:
        message = _format_progress_feedback(event)
        if not message:
            return
        _emit_task_feedback(
            chat_id,
            task_id=str(task_id or ""),
            text=message,
            kind="progress",
            state=state,
            reply_to_message_id=reply_to_message_id,
        )

    return _speak_callback, _progress_callback


def _extract_color_hint(text: str) -> str:
    normalized = _normalize_text(text)
    for color in _COLOR_HINTS:
        if re.search(rf"\b{re.escape(color)}\b", normalized):
            return color
    for token in re.findall(r"[a-z]+", normalized):
        if len(token) < 4:
            continue
        if token in _COLOR_ALIASES:
            return _COLOR_ALIASES[token]
        match = difflib.get_close_matches(token, list(_COLOR_HINTS), n=1, cutoff=0.72)
        if match:
            return match[0]
    return ""


def _looks_like_rgb_context(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(term in normalized for term in ("rgb", "keyboard", "lighting", "lights", "backlight", "color"))


def _extract_artifact_reference(result: str) -> str:
    text = str(result or "").strip()
    if not text:
        return ""

    line_prefixes = (
        "open target:",
        "entry file:",
        "project directory:",
        "saved to:",
        "opened:",
        "url:",
        "link:",
    )
    lines = [raw_line.strip() for raw_line in text.splitlines() if raw_line.strip()]
    for prefix in line_prefixes:
        for line in lines:
            lower = line.lower()
            if lower.startswith(prefix):
                value = line.split(":", 1)[1].strip()
                if value and value.lower() != "not identified":
                    return value

    url_match = re.search(r"(https?://\S+|file:///+\S+)", text)
    if url_match:
        return url_match.group(1).rstrip(").,")

    path_match = re.search(r"([A-Za-z]:\\[^\r\n]+)", text)
    if path_match:
        return path_match.group(1).strip()

    return ""


def _contextualize_task_goal(chat_id: str, text: str) -> str:
    original = str(text or "").strip()
    if not original:
        return original

    last_result = _last_task_result(chat_id)
    if not last_result:
        return original

    context_blob = (
        f"{str(last_result.get('goal', '')).strip()}\n"
        f"{str(last_result.get('result', '')).strip()}"
    )
    normalized = _normalize_text(original)
    color = _extract_color_hint(original)

    if color and _looks_like_rgb_context(context_blob) and (
        "it" in normalized or "back" in normalized or len(normalized.split()) <= 3
    ):
        return f"change the keyboard lighting to {color}"

    if re.search(r"\bopen (it|that|the game|the site|the app)\b", normalized):
        artifact = _extract_artifact_reference(str(last_result.get("result", "") or ""))
        if artifact:
            return f"open this artifact: {artifact}"

    return original


def _extract_json_object(text: str) -> dict:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        pass

    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _heuristic_plain_message_decision(text: str, chat_id: str = "") -> dict:
    original = str(text or "").strip()
    if _looks_like_chat_message(original):
        return {"kind": "chat", "goal": original, "source": "heuristic"}
    if _looks_like_task_request(original):
        return {
            "kind": "task",
            "goal": _contextualize_task_goal(chat_id, original),
            "source": "heuristic",
        }
    return {"kind": "chat", "goal": original, "source": "heuristic"}


def _llm_plain_message_decision(text: str, chat_id: str = "") -> dict:
    if not get_secret("gemini_api_key", ["GEMINI_API_KEY"]):
        return {}

    try:
        active_task = _active_task_snapshot(chat_id)
        last_result = _last_task_result(chat_id)

        context_parts = []
        if active_task:
            context_parts.append(
                "[ACTIVE TASK]\n"
                f"Task ID: {active_task.get('task_id', '')}\n"
                f"Goal: {str(active_task.get('goal', ''))[:260]}\n"
                f"Status: {active_task.get('status', '')}"
            )
        if last_result:
            context_parts.append(
                "[LAST TASK RESULT]\n"
                f"Task ID: {last_result.get('task_id', '')}\n"
                f"Goal: {str(last_result.get('goal', ''))[:260]}\n"
                f"Result:\n{str(last_result.get('result', ''))[:1200]}"
            )

        prompt = (
            "You are routing one Telegram message for AXIOM.\n"
            "Decide whether AXIOM should reply conversationally or execute work through its full task system.\n"
            "Choose \"task\" when the user wants AXIOM to do real work: run commands, control apps, operate browser, "
            "change settings, use hardware, research, build, fix, create files, use skills/agents, or continue a prior artifact/action.\n"
            "Choose \"chat\" for normal conversation, small talk, capability questions, status questions, clarification, or discussion.\n"
            "If the message refers to a previous task with pronouns like it/that, rewrite the goal explicitly when possible.\n"
            "Do not choose chat just because the message is short.\n\n"
            + ("\n\n".join(context_parts) + "\n\n" if context_parts else "")
            + f"[MESSAGE]\n{text.strip()}"
        )

        payload = gn.generate_json(
            prompt,
            model=gn.router_model_name(),
            schema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["chat", "task"]},
                    "goal": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["kind", "goal", "confidence", "reason"],
            },
        )
        if not payload:
            return {}
        kind = str(payload.get("kind", "") or "").strip().lower()
        if kind not in {"chat", "task"}:
            return {}
        goal = str(payload.get("goal", "") or text).strip() or str(text or "").strip()
        return {
            "kind": kind,
            "goal": goal,
            "confidence": float(payload.get("confidence", 0.0) or 0.0),
            "reason": str(payload.get("reason", "") or "").strip(),
            "source": "llm_router",
        }
    except Exception as error:
        log_event("telegram", "plain_message_router_error", str(error)[:500])
        return {}


def _decide_plain_message_action(text: str, chat_id: str = "") -> dict:
    original = str(text or "").strip()
    context_blocks = []
    active_task = _active_task_snapshot(chat_id)
    last_result = _last_task_result(chat_id)
    if active_task:
        context_blocks.append(
            f"Active task: {active_task.get('goal', '')} | status={active_task.get('status', '')}"
        )
    if last_result:
        context_blocks.append(
            f"Last task: {last_result.get('goal', '')} | result={str(last_result.get('result', ''))[:220]}"
        )
    router_decision = route_message_kind(original, context_blocks=context_blocks)
    mode = _plain_message_mode()
    if mode == "chat_only":
        return {"kind": "chat", "goal": original, "source": "chat_only"}
    if mode == "legacy":
        if router_decision.confidence >= 0.74:
            return {
                "kind": router_decision.kind,
                "goal": _contextualize_task_goal(chat_id, router_decision.rewritten_goal or original)
                if router_decision.kind == "task"
                else original,
                "source": router_decision.source,
            }
        return _heuristic_plain_message_decision(original, chat_id=chat_id)
    if mode == "operator":
        if _looks_like_explicit_tool_instruction(original):
            return {
                "kind": "task",
                "goal": _contextualize_task_goal(chat_id, original),
                "source": "operator_explicit_tool",
            }

        if (
            _looks_like_chat_message(original)
            or _looks_like_capability_question(original)
            or _looks_like_runtime_status_question(original)
        ):
            return {"kind": "chat", "goal": original, "source": "operator_chat_guard"}

        if router_decision.kind == "task" and router_decision.confidence >= 0.82:
            return {
                "kind": "task",
                "goal": _contextualize_task_goal(chat_id, router_decision.rewritten_goal or original),
                "source": router_decision.source,
            }
        if router_decision.kind == "chat" and router_decision.confidence >= 0.9:
            return {"kind": "chat", "goal": original, "source": router_decision.source}

        decision = _llm_plain_message_decision(original, chat_id=chat_id)
        if not decision:
            decision = _heuristic_plain_message_decision(original, chat_id=chat_id)

        if str(decision.get("kind", "")).strip().lower() == "task":
            decision["goal"] = _contextualize_task_goal(chat_id, str(decision.get("goal", original) or original))
            return decision

        if _looks_like_task_request(original) or (len(original.split()) <= 3 and not original.endswith("?")):
            return {
                "kind": "task",
                "goal": _contextualize_task_goal(chat_id, original),
                "source": "operator_default",
            }

        decision["goal"] = original
        return decision

    if router_decision.confidence >= 0.82:
        decision = {
            "kind": router_decision.kind,
            "goal": router_decision.rewritten_goal or original,
            "source": router_decision.source,
        }
    else:
        decision = _llm_plain_message_decision(original, chat_id=chat_id)
    if not decision:
        decision = _heuristic_plain_message_decision(original, chat_id=chat_id)

    if str(decision.get("kind", "")).strip().lower() == "task":
        decision["goal"] = _contextualize_task_goal(chat_id, str(decision.get("goal", original) or original))
    else:
        decision["goal"] = original
    return decision


def _generate_chat_reply(user_text: str, chat_id: str = "") -> str:
    api_key = get_secret("gemini_api_key", ["GEMINI_API_KEY"])
    if not api_key:
        return "Gemini is not configured yet, so Telegram chat replies are offline right now."

    try:
        from core import gemini_compat as genai

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
        if _looks_like_runtime_status_question(user_text):
            prompt_parts.append("[RECENT TASKS]\n" + _format_recent_tasks(limit=5))
        active_task = _active_task_snapshot(chat_id)
        if active_task:
            prompt_parts.append("[ACTIVE TASK]\n" + _format_active_task_status(chat_id))
        last_result = _last_task_result(chat_id)
        if last_result and _looks_like_task_followup(user_text):
            prompt_parts.append(
                "[LAST TASK RESULT]\n"
                f"Task ID: {last_result.get('task_id', '')}\n"
                f"Goal: {str(last_result.get('goal', ''))[:260]}\n"
                f"Result:\n{str(last_result.get('result', ''))[:1800]}"
            )

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
            reply = "I'm here. Send a clear instruction. I can either reply normally or execute the work directly."
        remember_conversation_turn(
            user_text,
            reply,
            channel="telegram",
            channel_scope=chat_id,
            metadata={"kind": "chat_reply"},
        )
        _persist_channel_state(
            chat_id,
            last_user_text=user_text,
            last_assistant_text=reply,
            metadata={"last_interaction": "chat_reply"},
        )
        log_event("telegram", "chat_reply", user_text[:300], metadata={"reply_preview": reply[:220]})
        return reply
    except Exception as error:
        log_event("telegram", "chat_reply_error", str(error)[:500])
        return "Telegram chat hit a model error just now, but execution is still available."


def _reply_to_chat(chat_id: str, text: str, reply_to_message_id: int | None) -> None:
    _send_message(chat_id, _generate_chat_reply(text, chat_id=chat_id), reply_to_message_id=reply_to_message_id)


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


def broadcast_bridge_message(text: str, chat_ids: list[str] | None = None) -> int:
    if not _is_enabled():
        return 0

    if chat_ids:
        targets = [str(chat_id).strip() for chat_id in chat_ids if str(chat_id).strip()]
    else:
        targets = sorted(_allowed_chat_ids())

    delivered = 0
    for chat_id in targets:
        try:
            _send_message(chat_id, text)
            delivered += 1
        except Exception as error:
            log_event(
                "telegram",
                "broadcast_failed",
                str(error)[:500],
                metadata={"chat_id": chat_id, "text_preview": str(text or "")[:200]},
            )
    if delivered:
        log_event("telegram", "broadcast_sent", str(text or "")[:500], metadata={"delivered": delivered})
    return delivered


def _format_recent_tasks(limit: int = 8) -> str:
    rows = recent_task_runs(limit=limit)
    if not rows:
        return "No recent task checkpoints recorded."

    lines = ["Recent task checkpoints"]
    for row in rows:
        metadata = dict(row.get("metadata") or {})
        phase = str(metadata.get("phase", "") or "").strip().lower()
        channel = str(metadata.get("channel", "") or "").strip().lower()
        extras = []
        if phase:
            extras.append(f"phase={phase}")
        if channel:
            extras.append(f"channel={channel}")
        lines.append(
            f"- [{row['task_id']}] {row['status']} | {row['goal'][:90]} | {row['updated_at']}"
            + (f" | {' '.join(extras)}" if extras else "")
        )
    return "\n".join(lines)


def _queue_task(
    chat_id: str,
    goal: str,
    reply_to_message_id: int | None,
    log_func: Callable | None,
    *,
    explicit: bool = False,
) -> None:
    def _on_complete(task_id: str, result: str) -> None:
        try:
            _ACTIVE_CHAT_TASKS.pop(chat_id, None)
            _LAST_CHAT_TASK_RESULTS[chat_id] = {
                "task_id": task_id,
                "goal": goal,
                "result": result,
            }
            final_text = _render_task_completion_message(result)
            _send_message(chat_id, final_text)
            remember_conversation_turn(
                goal,
                result,
                channel="telegram",
                channel_scope=chat_id,
                metadata={"kind": "task_result", "task_id": task_id},
            )
            _persist_channel_state(
                chat_id,
                active_task_id="",
                last_task_id=task_id,
                last_goal=goal,
                last_result=result,
                last_assistant_text=result,
                metadata={"last_interaction": "task_result", "task_id": task_id},
            )
            log_event("telegram", "task_finished", f"[{task_id}] {goal[:200]}")
        except Exception as send_error:
            log_event("telegram", "task_finish_send_failed", f"{task_id}: {send_error}")

    speak_callback, progress_callback = _build_task_feedback_callbacks(
        chat_id,
        reply_to_message_id=reply_to_message_id,
    )
    task_id = submit_channel_task(
        goal,
        channel="telegram",
        scope=chat_id,
        origin="telegram_bridge",
        priority=TaskPriority.NORMAL,
        speak=speak_callback,
        on_complete=_on_complete,
        on_progress=progress_callback,
        metadata={"interface": "telegram_bridge"},
    )
    _ACTIVE_CHAT_TASKS[chat_id] = task_id
    _persist_channel_state(
        chat_id,
        active_task_id=task_id,
        last_goal=goal,
        last_user_text=goal,
        metadata={"last_interaction": "task_queued", "task_id": task_id},
    )
    ack = _task_ack_message(goal, task_id, explicit=explicit)
    _send_message(chat_id, ack, reply_to_message_id=reply_to_message_id)
    log_event("telegram", "task_queued", f"[{task_id}] {goal[:200]}")
    if log_func:
        log_func(f"Telegram task queued: {goal[:120]}")


def _handle_message(message: dict, log_func: Callable | None = None) -> None:
    text = str(message.get("text") or "").strip()
    if not text:
        return

    chat = message.get("chat", {}) or {}
    chat_id = str(chat.get("id", "")).strip()
    if not chat_id:
        return

    log_event(
        "telegram",
        "incoming_message",
        text[:300],
        metadata={
            "chat_id": chat_id,
            "message_id": message.get("message_id"),
        },
    )

    if not _chat_is_authorized(chat_id):
        _send_message(chat_id, "This Telegram chat is not authorized for AXIOM.")
        log_event("telegram", "unauthorized_chat", chat_id)
        return

    _persist_channel_state(
        chat_id,
        last_user_text=text,
        metadata={"last_message_id": message.get("message_id")},
    )

    reply_to_message_id = message.get("message_id")
    execution_enabled = _chat_can_execute(chat_id)
    execution_lock_notice = (
        "Telegram execution is locked until this chat ID is added to "
        "channels.telegram.allowed_chat_ids."
    )

    if text in ("/start", "/help"):
        _send_message(
            chat_id,
            (
                "AXIOM Telegram bridge\n\n"
                "/status - capability summary\n"
                "/trading - trade daemon status\n"
                "/trading_start - start the persistent trade daemon\n"
                "/trading_stop - stop the persistent trade daemon\n"
                "/trading_run - force the next trade cycle immediately\n"
                "/tasks - recent task checkpoints\n"
                "/task <goal> - optional explicit force-execute\n"
                "Plain messages default to execution when they look actionable.\n"
                "Normal conversation still gets a normal reply.\n"
                f"Execution from this chat: {'enabled' if execution_enabled else 'locked'}"
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

    if text in ("/trading", "/trade", "/trading_status", "/trade_status"):
        _send_message(
            chat_id,
            trade_daemon_control({"action": "status"}),
            reply_to_message_id=reply_to_message_id,
        )
        return

    if text in ("/trading_start", "/trade_start"):
        if not execution_enabled:
            _send_message(chat_id, execution_lock_notice, reply_to_message_id=reply_to_message_id)
            log_event("telegram", "execution_blocked", text, metadata={"chat_id": chat_id})
            return
        _send_message(
            chat_id,
            trade_daemon_control({"action": "start"}),
            reply_to_message_id=reply_to_message_id,
        )
        return

    if text in ("/trading_stop", "/trade_stop"):
        if not execution_enabled:
            _send_message(chat_id, execution_lock_notice, reply_to_message_id=reply_to_message_id)
            log_event("telegram", "execution_blocked", text, metadata={"chat_id": chat_id})
            return
        _send_message(
            chat_id,
            trade_daemon_control({"action": "stop"}),
            reply_to_message_id=reply_to_message_id,
        )
        return

    if text in ("/trading_run", "/trade_run", "/trading_wake", "/trade_wake"):
        if not execution_enabled:
            _send_message(chat_id, execution_lock_notice, reply_to_message_id=reply_to_message_id)
            log_event("telegram", "execution_blocked", text, metadata={"chat_id": chat_id})
            return
        _send_message(
            chat_id,
            trade_daemon_control({"action": "run_once"}),
            reply_to_message_id=reply_to_message_id,
        )
        return

    if text.startswith("/task "):
        goal = text[6:].strip()
        if not goal:
            _send_message(chat_id, "Usage: /task <goal>", reply_to_message_id=reply_to_message_id)
            return
        active_task = _active_task_snapshot(chat_id)
        if active_task:
            _send_message(
                chat_id,
                (
                    "There is already an active task running for this chat.\n"
                    f"Goal: {str(active_task.get('goal', ''))[:260]}\n\n"
                    "Wait for that result before queueing another execution request."
                ),
                reply_to_message_id=reply_to_message_id,
            )
            return
        if not execution_enabled:
            _send_message(chat_id, execution_lock_notice, reply_to_message_id=reply_to_message_id)
            log_event("telegram", "execution_blocked", goal[:200], metadata={"chat_id": chat_id})
            return
        resolved_goal = _contextualize_task_goal(chat_id, goal)
        if resolved_goal != goal:
            log_event(
                "telegram",
                "task_goal_rewritten",
                resolved_goal[:300],
                metadata={"chat_id": chat_id, "original_goal": goal[:300]},
            )
        _queue_task(chat_id, resolved_goal, reply_to_message_id, log_func, explicit=True)
        return

    active_task = _active_task_snapshot(chat_id)
    if active_task and _looks_like_task_followup(text):
        _send_message(chat_id, _format_active_task_status(chat_id), reply_to_message_id=reply_to_message_id)
        return

    if _telegram_config().get("queue_plain_messages", True):
        decision = _decide_plain_message_action(text, chat_id=chat_id)
        kind = str(decision.get("kind", "chat") or "chat").strip().lower()
        goal = str(decision.get("goal", text) or text).strip() or text
        log_event(
            "telegram",
            "plain_message_routed",
            f"{kind}: {goal[:260]}",
            metadata={
                "chat_id": chat_id,
                "source": str(decision.get("source", "") or ""),
                "reason": str(decision.get("reason", "") or "")[:240],
                "confidence": decision.get("confidence", 0.0),
            },
        )
        if kind == "task":
            if active_task:
                _send_message(
                    chat_id,
                    (
                        "There is already an active task running for this chat.\n"
                        f"Goal: {str(active_task.get('goal', ''))[:260]}\n\n"
                        "I am not queueing a second execution on top of it. Wait for the current result first."
                    ),
                    reply_to_message_id=reply_to_message_id,
                )
                return
            if not execution_enabled:
                _send_message(chat_id, execution_lock_notice, reply_to_message_id=reply_to_message_id)
                log_event("telegram", "execution_blocked", goal[:200], metadata={"chat_id": chat_id})
                return
            if goal != text:
                log_event(
                    "telegram",
                    "task_goal_rewritten",
                    goal[:300],
                    metadata={"chat_id": chat_id, "original_goal": text[:300]},
                )
            _queue_task(chat_id, goal, reply_to_message_id, log_func, explicit=False)
            return

    _reply_to_chat(chat_id, text, reply_to_message_id)


def _poll_loop(log_func: Callable | None = None) -> None:
    offset = 0
    bridge_ready_logged = False
    log_event("telegram", "bridge_started", "Telegram bridge thread started.")
    if log_func:
        log_func("Telegram bridge started.")

    while not _STOP_EVENT.is_set():
        if not _is_enabled():
            bridge_ready_logged = False
            _STOP_EVENT.wait(3)
            continue

        poll_seconds = float(_telegram_config().get("poll_seconds", 1.5) or 1.5)
        try:
            if not bridge_ready_logged:
                details = _probe_bridge_state()
                username = str(details.get("bot_username", "") or "").strip()
                if username:
                    log_event("telegram", "bridge_ready", f"@{username}", metadata=details)
                    if log_func:
                        log_func(f"Telegram bridge ready: @{username}")
                else:
                    log_event("telegram", "bridge_probe", json.dumps(details, ensure_ascii=False)[:500])

                webhook_url = str(details.get("webhook_url", "") or "").strip()
                if webhook_url:
                    log_event(
                        "telegram",
                        "webhook_active",
                        webhook_url[:500],
                        metadata={"pending_update_count": details.get("pending_update_count", 0)},
                    )
                    if log_func:
                        log_func("Telegram webhook is active; polling may conflict until it is cleared.")

                bridge_ready_logged = True

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
        except requests.HTTPError as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            if status_code == 409:
                detail = "Telegram getUpdates conflict detected. Another poller or webhook is active."
                log_event("telegram", "bridge_conflict", detail)
                if log_func:
                    log_func(detail)
            else:
                detail = str(error)[:500]
                log_event("telegram", "bridge_error", detail)
            _STOP_EVENT.wait(5)
        except Exception as error:
            log_event("telegram", "bridge_error", str(error)[:500])
            _STOP_EVENT.wait(5)

    log_event("telegram", "bridge_stopped", "Telegram bridge thread stopped.")
    if log_func:
        log_func("Telegram bridge stopped.")


def start_telegram_bridge(log_func: Callable | None = None) -> bool:
    global _BRIDGE_THREAD
    with _BRIDGE_LOCK:
        if _BRIDGE_THREAD and _BRIDGE_THREAD.is_alive():
            return True
        _STOP_EVENT.clear()

        _BRIDGE_THREAD = threading.Thread(
            target=_poll_loop,
            kwargs={"log_func": log_func},
            daemon=True,
            name="AxiomTelegramBridge",
        )
        _BRIDGE_THREAD.start()
    return True


def stop_telegram_bridge(timeout: float = 5.0) -> None:
    global _BRIDGE_THREAD
    with _BRIDGE_LOCK:
        thread = _BRIDGE_THREAD
        if thread is None:
            return
        _STOP_EVENT.set()

    if thread.is_alive():
        thread.join(timeout=max(float(timeout or 0), 0.5))

    with _BRIDGE_LOCK:
        if _BRIDGE_THREAD is thread and not thread.is_alive():
            _BRIDGE_THREAD = None
