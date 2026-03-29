from actions.send_message import send_message
from core.comms_surface import (
    email_launch_instructions,
    format_comms_status,
    place_call_via_twilio,
    send_email_via_smtp,
    send_sms_via_twilio,
    telephony_launch_instructions,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def comms_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status") or "status").strip().lower()

    if action == "status":
        report = format_comms_status()
        log_event("communications", "comms_status", report[:2000])
        return report

    if action == "launch_instructions":
        report = f"{email_launch_instructions()}\n\n{telephony_launch_instructions()}"
        log_event("communications", "comms_launch_instructions", report[:2000])
        return report

    channel = str(
        params.get("channel", "")
        or params.get("platform", "")
        or params.get("mode", "")
        or action
    ).strip().lower()
    target = str(params.get("to", "") or params.get("receiver", "") or params.get("phone_number", "") or "").strip()
    subject = str(params.get("subject", "") or "").strip()
    message_text = str(
        params.get("message", "")
        or params.get("message_text", "")
        or params.get("body", "")
        or params.get("text", "")
        or ""
    ).strip()

    if channel in {"email", "mail"} or action == "email":
        result = send_email_via_smtp(target, subject, message_text)
    elif channel in {"sms", "text"} or action == "sms":
        result = send_sms_via_twilio(target, message_text)
    elif channel in {"call", "phone"} or action == "call":
        result = place_call_via_twilio(target, message_text or "AXIOM is calling.")
    else:
        result = send_message(
            {
                "receiver": target,
                "message_text": message_text,
                "platform": channel or "telegram",
            },
            response=None,
            player=player,
            session_memory=None,
        )

    log_event(
        "communications",
        "comms_action",
        result[:2000],
        metadata={"action": action, "channel": channel, "target": target},
    )
    if action in {"email", "sms", "call", "send", "message"}:
        try:
            save_to_nexus(
                "Communication Action",
                result[:2000],
                kind="communication",
                source="comms_control",
                metadata={"action": action, "channel": channel, "target": target},
            )
        except Exception:
            pass
    return result
