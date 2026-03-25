import json
import shutil
import sys
from pathlib import Path

import requests

from core.runtime_config import load_runtime_config, update_runtime_config


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def configure_deerflow(updates: dict) -> dict:
    return update_runtime_config({"deerflow": updates or {}})


def _deerflow_config() -> dict:
    return load_runtime_config().get("deerflow", {}) or {}


def _path_or_none(value: str | Path | None) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _first_existing_path(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except Exception:
            continue
    return None


def _safe_json_get(url: str, timeout: float = 8.0) -> tuple[bool, dict]:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return True, payload if isinstance(payload, dict) else {}
    except Exception:
        return False, {}


def _count_skill_files(skills_root: Path) -> int:
    if not skills_root.exists():
        return 0
    try:
        return sum(1 for path in skills_root.rglob("SKILL.md") if path.is_file())
    except Exception:
        return 0


def _gateway_url() -> str:
    cfg = _deerflow_config()
    value = (
        str(cfg.get("gateway_url", "") or "").strip()
        or str(cfg.get("url", "") or "").strip()
        or "http://127.0.0.1:2026"
    )
    return value.rstrip("/")


def _langgraph_url() -> str:
    cfg = _deerflow_config()
    configured = str(cfg.get("langgraph_url", "") or "").strip()
    if configured:
        return configured.rstrip("/")
    return _gateway_url().rstrip("/") + "/api/langgraph"


def resolve_deerflow_repo_path() -> Path | None:
    cfg = _deerflow_config()
    runtime = load_runtime_config()
    candidates = [
        _path_or_none(cfg.get("repo_path", "")),
        _path_or_none((runtime.get("skill_library", {}) or {}).get("deerflow_path", "")),
        Path.home() / "deer-flow_upstream",
        Path.home() / "deer-flow",
        Path.home() / "Axiom_research" / "external" / "deer-flow",
    ]
    repo = _first_existing_path([path for path in candidates if path is not None])
    if repo is None:
        return None
    if (repo / "README.md").exists() and (repo / "backend" / "pyproject.toml").exists():
        return repo
    return None


def collect_deerflow_status(limit: int = 5) -> dict:
    repo = resolve_deerflow_repo_path()
    gateway_url = _gateway_url()
    langgraph_url = _langgraph_url()
    reachable, health = _safe_json_get(f"{gateway_url}/health")

    models = {}
    skills = {}
    agents = {}
    if reachable:
        _, models = _safe_json_get(f"{gateway_url}/api/models")
        _, skills = _safe_json_get(f"{gateway_url}/api/skills")
        _, agents = _safe_json_get(f"{gateway_url}/api/agents")

    skills_root = repo / "skills" if repo else None
    config_path = repo / "config.yaml" if repo else None

    return {
        "repo_path": str(repo) if repo else "",
        "gateway_url": gateway_url,
        "langgraph_url": langgraph_url,
        "proxy_reachable": reachable,
        "health_status": str(health.get("status", "") or ""),
        "node_available": bool(shutil.which("node")),
        "uv_available": bool(shutil.which("uv")),
        "pnpm_available": bool(shutil.which("pnpm")),
        "config_path": str(config_path) if config_path and config_path.exists() else "",
        "skills_root": str(skills_root) if skills_root and skills_root.exists() else "",
        "local_skill_count": _count_skill_files(skills_root) if skills_root else 0,
        "models_count": len((models.get("models", []) or [])),
        "skills_count": len((skills.get("skills", []) or [])),
        "agents_count": len((agents.get("agents", []) or [])),
        "sample_models": [str(row.get("name", "")) for row in (models.get("models", []) or [])[: max(int(limit), 1)]],
        "sample_skills": [str(row.get("name", "")) for row in (skills.get("skills", []) or [])[: max(int(limit), 1)]],
        "sample_agents": [str(row.get("name", "")) for row in (agents.get("agents", []) or [])[: max(int(limit), 1)]],
    }


def format_deerflow_status(limit: int = 5) -> str:
    status = collect_deerflow_status(limit=limit)
    lines = [
        "DeerFlow integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"Gateway URL: {status['gateway_url']}",
        f"LangGraph URL: {status['langgraph_url']}",
        f"Proxy reachable: {'yes' if status['proxy_reachable'] else 'no'}",
        f"Node available: {'yes' if status['node_available'] else 'no'}",
        f"uv available: {'yes' if status['uv_available'] else 'no'}",
        f"pnpm available: {'yes' if status['pnpm_available'] else 'no'}",
        f"Config file present: {'yes' if status['config_path'] else 'no'}",
        f"Local DeerFlow skills: {status['local_skill_count']}",
    ]
    if status["proxy_reachable"]:
        lines.extend(
            [
                f"Remote models: {status['models_count']}",
                f"Remote skills: {status['skills_count']}",
                f"Remote agents: {status['agents_count']}",
            ]
        )
        if status["sample_models"]:
            lines.append("Models: " + ", ".join(status["sample_models"]))
        if status["sample_skills"]:
            lines.append("Skills: " + ", ".join(status["sample_skills"]))
        if status["sample_agents"]:
            lines.append("Agents: " + ", ".join(status["sample_agents"]))
    return "\n".join(lines)


def deerflow_launch_instructions() -> str:
    status = collect_deerflow_status(limit=3)
    if not status["repo_path"]:
        return (
            "DeerFlow repo was not found. Clone it under C:/Users/moyes/deer-flow_upstream "
            "or set deerflow.repo_path in runtime.local.json."
        )
    if status["proxy_reachable"]:
        return (
            f"DeerFlow is already reachable at {status['gateway_url']}.\n"
            "Use deerflow_control with action='query' to send work into the harness."
        )
    return (
        "DeerFlow is installed but not running.\n"
        f"Repo: {status['repo_path']}\n"
        "Typical local start:\n"
        f"1. cd {status['repo_path']}\n"
        "2. make config\n"
        "3. edit config.yaml with at least one model/provider\n"
        "4. make dev\n"
        "5. open http://localhost:2026"
    )


def _mode_context(mode: str) -> dict:
    normalized = str(mode or "pro").strip().lower()
    mapping = {
        "flash": {"thinking_enabled": False, "is_plan_mode": False, "subagent_enabled": False},
        "standard": {"thinking_enabled": True, "is_plan_mode": False, "subagent_enabled": False},
        "pro": {"thinking_enabled": True, "is_plan_mode": True, "subagent_enabled": False},
        "ultra": {"thinking_enabled": True, "is_plan_mode": True, "subagent_enabled": True},
    }
    return mapping.get(normalized, mapping["pro"])


def _iter_sse_events(response) -> list[dict]:
    events = []
    current_event = "message"
    data_lines: list[str] = []

    for raw_line in response.iter_lines(decode_unicode=True):
        if raw_line is None:
            continue
        line = str(raw_line).rstrip("\r")
        if not line:
            if data_lines:
                events.append({"event": current_event, "data": "\n".join(data_lines)})
            current_event = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            current_event = line[6:].strip() or "message"
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    if data_lines:
        events.append({"event": current_event, "data": "\n".join(data_lines)})
    return events


def _extract_content_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = str(item.get("text", "") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        return str(content.get("text", "") or content.get("content", "") or "").strip()
    return ""


def _extract_ai_text_from_values(payload: dict) -> str:
    messages = payload.get("messages", []) or []
    ai_messages = []
    for message in messages:
        message_type = str(message.get("type", "") or message.get("role", "") or "").strip().lower()
        if message_type not in {"ai", "assistant"}:
            continue
        text = _extract_content_text(message.get("content", ""))
        if text:
            ai_messages.append(text)
    return ai_messages[-1] if ai_messages else ""


def run_deerflow_query(prompt: str, mode: str = "pro", thread_id: str = "", timeout: int = 240) -> dict:
    prompt = str(prompt or "").strip()
    if not prompt:
        return {"ok": False, "message": "Please provide a prompt for DeerFlow."}

    status = collect_deerflow_status(limit=3)
    if not status["proxy_reachable"]:
        return {
            "ok": False,
            "message": f"DeerFlow is not reachable at {status['gateway_url']}.",
            "thread_id": "",
        }

    resolved_thread_id = str(thread_id or "").strip()
    langgraph_url = status["langgraph_url"]
    if not resolved_thread_id:
        try:
            response = requests.post(f"{langgraph_url}/threads", json={}, timeout=20)
            response.raise_for_status()
            payload = response.json() or {}
            resolved_thread_id = str(payload.get("thread_id", "") or "").strip()
        except Exception as error:
            return {
                "ok": False,
                "message": f"DeerFlow thread creation failed: {error}",
                "thread_id": "",
            }
    if not resolved_thread_id:
        return {"ok": False, "message": "DeerFlow did not return a thread id.", "thread_id": ""}

    payload = {
        "assistant_id": "lead_agent",
        "input": {
            "messages": [
                {
                    "type": "human",
                    "content": [{"type": "text", "text": prompt}],
                }
            ]
        },
        "stream_mode": ["values", "messages-tuple"],
        "stream_subgraphs": True,
        "config": {"recursion_limit": 1000},
        "context": {**_mode_context(mode), "thread_id": resolved_thread_id},
    }

    try:
        response = requests.post(
            f"{langgraph_url}/threads/{resolved_thread_id}/runs/stream",
            json=payload,
            stream=True,
            timeout=(20, int(timeout)),
        )
        response.raise_for_status()
    except Exception as error:
        return {
            "ok": False,
            "message": f"DeerFlow run failed to start: {error}",
            "thread_id": resolved_thread_id,
        }

    run_id = ""
    final_text = ""
    events = []
    try:
        for event in _iter_sse_events(response):
            events.append(event)
            event_type = event.get("event", "")
            data = event.get("data", "")
            if event_type == "metadata":
                try:
                    metadata = json.loads(data)
                    run_id = str(metadata.get("run_id", "") or run_id)
                except Exception:
                    pass
            elif event_type == "values":
                try:
                    values = json.loads(data)
                    candidate = _extract_ai_text_from_values(values)
                    if candidate:
                        final_text = candidate
                except Exception:
                    continue
    finally:
        response.close()

    if not final_text:
        return {
            "ok": False,
            "message": "DeerFlow completed without a readable AI response.",
            "thread_id": resolved_thread_id,
            "run_id": run_id,
        }

    return {
        "ok": True,
        "thread_id": resolved_thread_id,
        "run_id": run_id,
        "mode": str(mode or "pro").strip().lower(),
        "response_text": final_text,
        "events_count": len(events),
    }
