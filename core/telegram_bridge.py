import threading
import time
import re
import difflib
import json
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
_PLAIN_MESSAGE_MODES = {"operator", "smart", "legacy", "chat_only"}


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


def _api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{_telegram_token()}/{method}"


def _channel_state(chat_id: str) -> dict:
    return get_channel_state("telegram", str(chat_id or "").strip())


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
            "can you access",
            "can u access",
            "can you deploy",
            "can u deploy",
            "do you have access",
            "do u have access",
        )
    ) or (
        any(
            token in normalized
            for token in (
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
            )
        )
        and any(token in normalized for token in ("can you", "can u", "do you", "do u", "able to", "access", "deploy", "use"))
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
    return (
        f"Active task [{status['task_id']}]\n"
        f"Status: {status['status']}\n"
        f"Goal: {str(status.get('goal', ''))[:260]}"
    )


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
        return f"Queued it.\n\nTask ID: {task_id}\nGoal: {goal[:300]}".strip()
    if any(term in normalized for term in ("keyboard", "lighting", "backlight", "rgb", "lights")):
        return "Changing that now."
    if normalized.startswith(("open ", "launch ", "start ")):
        return "Opening that now."
    if normalized.startswith(("close ", "kill ", "restart ", "shutdown ")):
        return "Handling that now."
    if normalized.startswith(("search ", "look up ", "research ", "analyze ", "summarize ")):
        return "Running that now."
    if normalized.startswith(("create ", "build ", "make ", "write ", "deploy ", "fix ")):
        return "Working on that now."
    return "On it."


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
    api_key = get_secret("gemini_api_key", ["GEMINI_API_KEY"])
    if not api_key:
        return {}

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
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
            "Return strict JSON only with this schema:\n"
            "{\"kind\":\"chat|task\",\"goal\":\"rewritten explicit task or original message\",\"confidence\":0.0,\"reason\":\"short reason\"}\n\n"
            "Choose \"task\" when the user wants AXIOM to do real work: run commands, control apps, operate browser, "
            "change settings, use hardware, research, build, fix, create files, use skills/agents, or continue a prior artifact/action.\n"
            "Choose \"chat\" for normal conversation, small talk, capability questions, status questions, clarification, or discussion.\n"
            "If the message refers to a previous task with pronouns like it/that, rewrite the goal explicitly when possible.\n"
            "Do not choose chat just because the message is short.\n\n"
            + ("\n\n".join(context_parts) + "\n\n" if context_parts else "")
            + f"[MESSAGE]\n{text.strip()}"
        )

        model = genai.GenerativeModel(_text_model_name())
        response = model.generate_content(prompt)
        payload = _extract_json_object(getattr(response, "text", "") or "")
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
    mode = _plain_message_mode()
    if mode == "chat_only":
        return {"kind": "chat", "goal": original, "source": "chat_only"}
    if mode == "legacy":
        return _heuristic_plain_message_decision(original, chat_id=chat_id)
    if mode == "operator":
        if (
            _looks_like_chat_message(original)
            or _looks_like_capability_question(original)
            or _looks_like_runtime_status_question(original)
        ):
            return {"kind": "chat", "goal": original, "source": "operator_chat_guard"}

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


def _queue_task(
    chat_id: str,
    goal: str,
    reply_to_message_id: int | None,
    log_func: Callable | None,
    *,
    explicit: bool = False,
) -> None:
    queue = get_queue()

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

    task_id = queue.submit(
        goal=goal,
        priority=TaskPriority.NORMAL,
        speak=None,
        on_complete=_on_complete,
        metadata={
            "channel": "telegram",
            "scope": chat_id,
            "origin": "telegram_bridge",
        },
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
        log_func(f"Telegram executing task [{task_id}]")


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
                    f"Task [{active_task['task_id']}] is already running for this chat.\n"
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
                        f"Task [{active_task['task_id']}] is already running for this chat.\n"
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
