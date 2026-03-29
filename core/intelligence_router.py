import json
import re
from dataclasses import dataclass

import requests

from core.runtime_config import load_runtime_config


_TASK_HINTS = (
    "open ",
    "run ",
    "use ",
    "create ",
    "make ",
    "change ",
    "set ",
    "turn ",
    "close ",
    "restart ",
    "shutdown ",
    "search ",
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
    "organize ",
    "trade ",
    "buy ",
    "sell ",
    "find ",
)
_CHAT_HINTS = (
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank you",
    "who are you",
    "what can you do",
    "how are you",
)


@dataclass(frozen=True)
class RouteDecision:
    kind: str
    confidence: float
    source: str
    reason: str = ""
    rewritten_goal: str = ""


def _routing_config() -> dict:
    return load_runtime_config().get("routing", {}) or {}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _simple_request_max_words() -> int:
    cfg = _routing_config()
    return max(int(cfg.get("simple_request_max_words", 18) or 18), 6)


def _heuristic_message_route(text: str) -> RouteDecision:
    normalized = _normalize_text(text)
    if not normalized:
        return RouteDecision(kind="chat", confidence=0.9, source="heuristic", reason="empty")

    if normalized in _CHAT_HINTS:
        return RouteDecision(kind="chat", confidence=0.95, source="heuristic", reason="chat phrase")

    if any(normalized.startswith(prefix) for prefix in _TASK_HINTS):
        return RouteDecision(kind="task", confidence=0.9, source="heuristic", reason="task verb", rewritten_goal=text.strip())

    if normalized.endswith("?") and len(normalized.split()) <= _simple_request_max_words():
        return RouteDecision(kind="chat", confidence=0.78, source="heuristic", reason="short question")

    if len(normalized.split()) <= 3 and not normalized.endswith("?"):
        return RouteDecision(kind="task", confidence=0.74, source="heuristic", reason="short imperative", rewritten_goal=text.strip())

    return RouteDecision(kind="chat", confidence=0.55, source="heuristic", reason="default")


def _ollama_available() -> bool:
    cfg = _routing_config()
    endpoint = str(cfg.get("local_endpoint", "http://127.0.0.1:11434") or "").strip().rstrip("/")
    if not endpoint:
        return False
    try:
        response = requests.get(f"{endpoint}/api/tags", timeout=1.8)
        return response.ok
    except Exception:
        return False


def _ollama_route(text: str, context_blocks: list[str] | None = None) -> RouteDecision | None:
    cfg = _routing_config()
    if not bool(cfg.get("prefer_local_classifier", True)):
        return None
    if str(cfg.get("local_provider", "ollama") or "").strip().lower() != "ollama":
        return None
    if not _ollama_available():
        return None

    endpoint = str(cfg.get("local_endpoint", "http://127.0.0.1:11434") or "").strip().rstrip("/")
    model = str(cfg.get("local_model", "qwen2.5:7b-instruct") or "").strip() or "qwen2.5:7b-instruct"
    timeout_seconds = float(cfg.get("classifier_timeout_seconds", 5.0) or 5.0)
    context_text = "\n\n".join(block for block in (context_blocks or []) if str(block or "").strip())
    prompt = (
        "Classify one AXIOM request.\n"
        "Return strict JSON only.\n"
        '{"kind":"chat|task","confidence":0.0,"reason":"short reason","goal":"rewritten explicit task or original message"}\n'
        "Choose task when the user wants real execution, research, coding, browser work, desktop control, "
        "file operations, market analysis, or continuing a prior artifact.\n"
        "Choose chat for normal conversation, small talk, status questions, or capability questions.\n"
    )
    if context_text:
        prompt += f"\n[CONTEXT]\n{context_text}\n"
    prompt += f"\n[MESSAGE]\n{text.strip()}\n"

    try:
        response = requests.post(
            f"{endpoint}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json() or {}
        raw = str(payload.get("response", "") or "").strip()
        if not raw:
            return None
        data = json.loads(raw)
        kind = str(data.get("kind", "") or "").strip().lower()
        if kind not in {"chat", "task"}:
            return None
        return RouteDecision(
            kind=kind,
            confidence=float(data.get("confidence", 0.0) or 0.0),
            source="ollama_router",
            reason=str(data.get("reason", "") or "").strip(),
            rewritten_goal=str(data.get("goal", "") or text).strip(),
        )
    except Exception:
        return None


def route_message_kind(text: str, context_blocks: list[str] | None = None) -> RouteDecision:
    heuristic = _heuristic_message_route(text)
    local = _ollama_route(text, context_blocks=context_blocks)
    if local and local.confidence >= heuristic.confidence:
        return local
    return heuristic


def format_routing_status() -> str:
    cfg = _routing_config()
    return (
        "[ROUTING STATUS]\n"
        f"- Local classifier preferred: {'yes' if cfg.get('prefer_local_classifier', True) else 'no'}\n"
        f"- Local provider: {cfg.get('local_provider', 'ollama')}\n"
        f"- Local endpoint: {cfg.get('local_endpoint', 'http://127.0.0.1:11434')}\n"
        f"- Local model: {cfg.get('local_model', 'qwen2.5:7b-instruct')}\n"
        f"- Ollama reachable: {'yes' if _ollama_available() else 'no'}\n"
        f"- Simple request cutoff: {_simple_request_max_words()} words"
    )
