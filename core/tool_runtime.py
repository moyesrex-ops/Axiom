import importlib
import inspect
import time
from dataclasses import dataclass
from typing import Any, Callable

from memory.runtime_store import log_event, log_failure, record_tool_trace


@dataclass(frozen=True)
class ToolBinding:
    module_path: str
    attribute: str
    default_result: str = "Done."


_TOOL_BINDINGS: dict[str, ToolBinding] = {
    "open_app": ToolBinding("actions.open_app", "open_app"),
    "web_search": ToolBinding("actions.web_search", "web_search", "Search completed."),
    "browser_control": ToolBinding("actions.browser_control", "browser_control", "Browser action completed."),
    "gemini_native": ToolBinding("actions.gemini_native", "gemini_native"),
    "file_controller": ToolBinding("actions.file_controller", "file_controller", "File operation completed."),
    "cmd_control": ToolBinding("actions.cmd_control", "cmd_control", "Command executed."),
    "code_helper": ToolBinding("actions.code_helper", "code_helper"),
    "dev_agent": ToolBinding("actions.dev_agent", "dev_agent"),
    "codex_builder": ToolBinding("actions.codex_builder", "codex_builder"),
    "screen_process": ToolBinding("actions.vision_engine", "vision_tool"),
    "vision_tool": ToolBinding("actions.vision_engine", "vision_tool"),
    "send_message": ToolBinding("actions.send_message", "send_message"),
    "reminder": ToolBinding("actions.reminder", "reminder"),
    "youtube_video": ToolBinding("actions.youtube_video", "youtube_video"),
    "weather_report": ToolBinding("actions.weather_report", "weather_action"),
    "computer_settings": ToolBinding("actions.computer_settings", "computer_settings"),
    "desktop_control": ToolBinding("actions.desktop", "desktop_control"),
    "computer_control": ToolBinding("actions.computer_control", "computer_control"),
    "computer_use": ToolBinding("actions.computer_use", "computer_use"),
    "flight_finder": ToolBinding("actions.flight_finder", "flight_finder"),
    "memory_archive": ToolBinding("actions.nexus_memory", "memory_archive"),
    "nexus_memory": ToolBinding("actions.nexus_memory", "memory_archive"),
    "deep_analyzer": ToolBinding("actions.deep_analyzer", "deep_analyzer"),
    "autonomous_researcher": ToolBinding("actions.autonomous_researcher", "autonomous_research"),
    "mt5_trading": ToolBinding("actions.mt5_trading_agent", "mt5_trading"),
    "predict_market": ToolBinding("actions.market_predictor", "predict_market"),
    "mirofish_control": ToolBinding("actions.mirofish_control", "mirofish_control"),
    "tradingagents_control": ToolBinding("actions.tradingagents_control", "tradingagents_control"),
    "self_modifier": ToolBinding("actions.self_modifier", "self_modifier"),
    "system_capabilities": ToolBinding("actions.system_capabilities", "system_capabilities"),
    "automaton_control": ToolBinding("actions.automaton_control", "automaton_control"),
    "skill_library": ToolBinding("actions.skill_library", "skill_library"),
    "agent_library": ToolBinding("actions.agent_library", "agent_library"),
    "lightpanda_control": ToolBinding("actions.lightpanda_control", "lightpanda_control"),
    "autoresearch_control": ToolBinding("actions.autoresearch_control", "autoresearch_control"),
    "deerflow_control": ToolBinding("actions.deerflow_control", "deerflow_control"),
    "paperclip_control": ToolBinding("actions.paperclip_control", "paperclip_control"),
    "openfang_control": ToolBinding("actions.openfang_control", "openfang_control"),
    "symphony_control": ToolBinding("actions.symphony_control", "symphony_control"),
    "lossless_claw_control": ToolBinding("actions.lossless_claw_control", "lossless_claw_control"),
    "dexter_control": ToolBinding("actions.dexter_control", "dexter_control"),
    "pentagi_control": ToolBinding("actions.pentagi_control", "pentagi_control"),
    "persona_control": ToolBinding("actions.persona_control", "persona_control"),
    "prompt_studio": ToolBinding("actions.prompt_studio", "prompt_studio"),
    "lead_researcher": ToolBinding("actions.lead_researcher", "lead_researcher"),
    "swarm_orchestrator": ToolBinding("actions.swarm_orchestrator", "swarm_orchestrator"),
    "crucix_control": ToolBinding("actions.crucix_control", "crucix_control"),
}


def list_registered_tools() -> list[str]:
    return sorted(_TOOL_BINDINGS.keys())


def has_tool_binding(name: str) -> bool:
    tool_name = str(name or "").strip()
    if tool_name in _TOOL_BINDINGS:
        return True
    try:
        from actions.self_modifier import get_dynamic_tool

        return get_dynamic_tool(tool_name) is not None
    except Exception:
        return False


def _resolve_callable(name: str) -> tuple[Callable[..., Any], str]:
    tool_name = str(name or "").strip()
    binding = _TOOL_BINDINGS.get(tool_name)
    if binding is not None:
        module = importlib.import_module(binding.module_path)
        return getattr(module, binding.attribute), binding.default_result

    from actions.self_modifier import get_dynamic_tool

    dynamic_tool = get_dynamic_tool(tool_name)
    if dynamic_tool is not None:
        return dynamic_tool, "Done."

    raise ValueError(f"Unknown tool: {tool_name}")


def _normalize_parameters(tool_name: str, parameters: dict | None) -> dict:
    params = dict(parameters or {})

    if tool_name == "screen_process":
        if "action" not in params:
            params["action"] = "analyze"
        angle = str(params.get("angle", "") or "").strip().lower()
        if angle and "source" not in params:
            params["source"] = "camera" if angle == "camera" else "screen"

    if tool_name == "computer_use" and "description" not in params:
        if params.get("goal") not in (None, ""):
            params["description"] = params.get("goal")

    return params


def _build_call_kwargs(
    func: Callable[..., Any],
    *,
    parameters: dict,
    response: Any,
    player: Any,
    session_memory: Any,
    speak: Callable | None,
) -> dict:
    signature = inspect.signature(func)
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    available = {
        "parameters": parameters,
        "response": response,
        "player": player,
        "session_memory": session_memory,
        "speak": speak,
    }
    if accepts_kwargs:
        return dict(available)
    return {
        name: value
        for name, value in available.items()
        if name in signature.parameters
    }


def execute_tool(
    name: str,
    parameters: dict | None = None,
    *,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
    speak: Callable | None = None,
    channel: str = "",
    scope: str = "",
    source: str = "",
    metadata: dict | None = None,
) -> str:
    tool_name = str(name or "").strip()
    if not tool_name:
        raise ValueError("Tool name is required.")

    params = _normalize_parameters(tool_name, parameters)
    started_at = time.perf_counter()
    result_text = ""
    error_text = ""
    success = False

    log_event(
        "tool",
        "call_start",
        f"{tool_name}({str(params)[:500]})",
        metadata={
            "tool": tool_name,
            "channel": str(channel or ""),
            "scope": str(scope or ""),
            "source": str(source or ""),
            **(metadata or {}),
        },
    )

    try:
        func, default_result = _resolve_callable(tool_name)
        call_kwargs = _build_call_kwargs(
            func,
            parameters=params,
            response=response,
            player=player,
            session_memory=session_memory,
            speak=speak,
        )
        result = func(**call_kwargs)
        result_text = str(result or default_result or "Done.").strip() or "Done."
        success = True
        return result_text
    except Exception as exc:
        error_text = str(exc)
        log_failure(tool_name, str(params)[:500], error_text[:2000])
        raise
    finally:
        duration_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        trace_metadata = dict(metadata or {})
        trace_metadata["tool"] = tool_name
        record_tool_trace(
            tool=tool_name,
            args=params,
            result_text=result_text,
            success=success,
            duration_ms=duration_ms,
            channel=channel,
            scope=scope,
            source=source,
            error_text=error_text,
            metadata=trace_metadata,
        )
        topic = "call_end" if success else "call_error"
        content = (
            f"{tool_name} completed in {duration_ms}ms"
            if success
            else f"{tool_name} failed in {duration_ms}ms: {error_text[:300]}"
        )
        log_event(
            "tool",
            topic,
            content,
            metadata={
                "tool": tool_name,
                "success": success,
                "duration_ms": duration_ms,
                "channel": str(channel or ""),
                "scope": str(scope or ""),
                "source": str(source or ""),
                **(metadata or {}),
            },
        )
