import json

from actions.computer_control import computer_control
from actions.vision_engine import (
    analyze_screen,
    find_element,
    read_text_on_screen,
    verify_action,
)
from core.runtime_config import load_runtime_config
from memory.runtime_store import log_event


def _computer_use_config() -> dict:
    return load_runtime_config().get("computer_use", {}) or {}


def _confirm_if_needed(action: str, params: dict) -> str:
    cfg = _computer_use_config()
    physical_actions = {
        "click",
        "move",
        "type",
        "hotkey",
        "find_and_click",
        "find_and_type",
    }
    if action not in physical_actions:
        return ""
    if not bool(cfg.get("confirm_physical_actions", False)):
        return ""
    if bool(params.get("confirm", False)):
        return ""
    return (
        "computer_use physical control is configured to require confirmation. "
        "Retry with confirm=true or disable computer_use.confirm_physical_actions in runtime config."
    )


def _delegate_computer_control(action: str, params: dict) -> str:
    forwarded = dict(params)
    forwarded["action"] = action
    return computer_control(parameters=forwarded, player=None)


def computer_use(parameters: dict = None, player=None, speak=None) -> str:
    params = dict(parameters or {})
    action = str(params.get("action", "observe")).strip().lower() or "observe"
    confirmation_error = _confirm_if_needed(action, params)
    if confirmation_error:
        return confirmation_error

    if action in {"screenshot", "move", "click", "type", "hotkey", "info"}:
        mapped_action = "screen_size" if action == "info" else action
        return _delegate_computer_control(mapped_action, params)

    if action in {"observe", "analyze"}:
        question = str(params.get("question", "") or params.get("text", "") or params.get("description", "") or "What is visible on the screen?").strip()
        source = str(params.get("source", "screen") or "screen").strip().lower()
        result = analyze_screen(question=question, source=source)
        report = result.description if result.description else json.dumps(result.to_dict(), ensure_ascii=False)
        log_event("computer_use", "observe", report[:2000], metadata={"source": source})
        return report

    if action == "read_text":
        text = read_text_on_screen()
        log_event("computer_use", "read_text", text[:2000])
        return text

    if action == "find":
        description = str(params.get("description", "") or params.get("question", "") or params.get("text", "")).strip()
        if not description:
            return "Please provide description for computer_use find."
        source = str(params.get("source", "screen") or "screen").strip().lower()
        result = find_element(description, source=source)
        report = json.dumps(result, indent=2, ensure_ascii=False)
        log_event("computer_use", "find", report[:2000], metadata={"description": description, "source": source})
        return report

    if action == "find_and_click":
        description = str(params.get("description", "") or params.get("question", "") or params.get("text", "")).strip()
        if not description:
            return "Please provide description for computer_use find_and_click."
        result = _delegate_computer_control("screen_click", {"description": description})
        log_event("computer_use", "find_and_click", result[:2000], metadata={"description": description})
        return result

    if action == "find_and_type":
        description = str(params.get("description", "") or params.get("field_description", "") or params.get("question", "")).strip()
        text = str(params.get("text", "") or "").strip()
        clear_first = bool(params.get("clear_first", True))
        if not description:
            return "Please provide description for the target field."
        if not text:
            return "Please provide text to type."
        click_result = _delegate_computer_control("screen_click", {"description": description})
        if "Could not find" in click_result or "NOT_FOUND" in click_result:
            return click_result
        type_result = _delegate_computer_control("smart_type", {"text": text, "clear_first": clear_first})
        report = f"{click_result}\n{type_result}"
        log_event(
            "computer_use",
            "find_and_type",
            report[:2000],
            metadata={"description": description, "text_preview": text[:120]},
        )
        return report

    if action == "verify":
        expected = str(params.get("expected", "") or params.get("description", "") or params.get("question", "")).strip()
        if not expected:
            return "Please provide expected outcome for computer_use verify."
        timeout = float(params.get("seconds", _computer_use_config().get("default_verify_seconds", 1.2)) or 1.2)
        result = verify_action(expected_outcome=expected, timeout=timeout)
        report = json.dumps(result, indent=2, ensure_ascii=False)
        log_event("computer_use", "verify", report[:2000], metadata={"expected": expected, "timeout": timeout})
        return report

    return (
        "Unknown action. Use observe, analyze, read_text, find, find_and_click, "
        "find_and_type, verify, screenshot, move, click, type, hotkey, or info."
    )
