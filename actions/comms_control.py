from actions.send_message import send_message
from core.comms_surface import (
    email_launch_instructions,
    format_comms_status,
    place_call_via_twilio,
    send_email_via_smtp,
    send_sms_via_twilio,
    telephony_launch_instructions,
)
from core.google_workspace import (
    calendar_create_event,
    calendar_list_upcoming_events,
    collect_google_workspace_status,
    gmail_generate_reply,
    gmail_list_recent_messages,
    gmail_read_message,
    gmail_reply_to_message,
    plan_calendar_event_from_text,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def _int_value(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _listify(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raw = str(value or "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _format_recent_mail(payload: dict) -> str:
    rows = list(payload.get("messages") or [])
    if not rows:
        return "No matching Gmail messages were found."

    lines = [f"[GMAIL] {len(rows)} message(s)"]
    for row in rows:
        unread = "UNREAD" if "UNREAD" in list(row.get("label_ids") or []) else "READ"
        lines.append(
            f"- {row.get('id', '')} | {unread} | {row.get('from', '')} | {row.get('subject', '')} | {row.get('date', '')}"
        )
    return "\n".join(lines)


def _format_mail_message(message: dict) -> str:
    body = str(message.get("body_text", "") or "").strip() or str(message.get("snippet", "") or "").strip()
    lines = [
        "[GMAIL MESSAGE]",
        f"ID: {message.get('id', '')}",
        f"Thread: {message.get('thread_id', '')}",
        f"From: {message.get('from', '')}",
        f"To: {message.get('to', '')}",
        f"Subject: {message.get('subject', '')}",
        f"Date: {message.get('date', '')}",
        "",
        body[:6000] or "(empty body)",
    ]
    return "\n".join(lines)


def _format_calendar_events(payload: dict) -> str:
    rows = list(payload.get("events") or [])
    if not rows:
        return "No upcoming calendar events were found."
    lines = [f"[CALENDAR] {len(rows)} upcoming event(s)"]
    for row in rows:
        lines.append(
            f"- {row.get('summary', '')} | {row.get('start', '')} -> {row.get('end', '')} | {row.get('location', '')}"
        )
    return "\n".join(lines)


def _resolve_message_id(params: dict) -> str:
    message_id = str(params.get("message_id", "") or params.get("id", "") or "").strip()
    if message_id:
        return message_id
    payload = gmail_list_recent_messages(
        limit=1,
        query=str(params.get("query", "") or "").strip(),
        unread_only=bool(params.get("unread_only", True)),
    )
    rows = list(payload.get("messages") or [])
    if not rows:
        raise RuntimeError("No matching Gmail message was found to act on.")
    return str(rows[0].get("id", "") or "").strip()


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

    if action in {"workspace_status", "gmail_status", "calendar_status"}:
        status = collect_google_workspace_status()
        report = (
            "[GOOGLE WORKSPACE]\n"
            f"- Ready: {'yes' if status['ready'] else 'no'}\n"
            f"- Enabled: {'yes' if status['enabled'] else 'no'}\n"
            f"- Gmail enabled: {'yes' if status['gmail_enabled'] else 'no'}\n"
            f"- Calendar enabled: {'yes' if status['calendar_enabled'] else 'no'}\n"
            f"- Client secret: {status['client_secret_path'] or 'not configured'}\n"
            f"- Token path: {status['token_path']}\n"
            f"- Timezone: {status['timezone']}"
        )
        log_event("communications", "google_workspace_status", report[:2000])
        return report

    if action in {"gmail_recent", "gmail_check", "check_mail", "check_email"}:
        payload = gmail_list_recent_messages(
            limit=_int_value(params.get("count", params.get("limit", 8)), 8),
            query=str(params.get("query", "") or "").strip(),
            unread_only=bool(params.get("unread_only", True)),
        )
        report = _format_recent_mail(payload)
        log_event("communications", "gmail_recent", report[:2000], metadata={"count": payload.get("count", 0)})
        return report

    if action in {"gmail_read", "email_read"}:
        message = gmail_read_message(_resolve_message_id(params))
        report = _format_mail_message(message)
        log_event("communications", "gmail_read", report[:2000], metadata={"message_id": message.get("id", "")})
        return report

    if action in {"gmail_reply_draft", "gmail_reply_send"}:
        message_id = _resolve_message_id(params)
        instruction = str(params.get("instruction", "") or "").strip()
        body_text = str(
            params.get("body", "")
            or params.get("message", "")
            or params.get("message_text", "")
            or ""
        ).strip()
        if not body_text:
            message = gmail_read_message(message_id)
            body_text = gmail_generate_reply(message, instruction=instruction)
        payload = gmail_reply_to_message(
            message_id,
            body_text,
            send=(action == "gmail_reply_send" or bool(params.get("send", False))),
        )
        report = (
            f"Gmail reply {payload.get('mode', 'prepared')} for {payload.get('to', '')}. "
            f"Subject: {payload.get('subject', '')}"
        )
        log_event("communications", "gmail_reply", report[:2000], metadata=payload)
        save_to_nexus(
            "Gmail Reply",
            body_text[:2000],
            kind="communication",
            source="comms_control",
            metadata={"action": action, "message_id": message_id, **payload},
        )
        return report

    if action in {"calendar_list", "calendar_upcoming"}:
        payload = calendar_list_upcoming_events(
            limit=_int_value(params.get("count", params.get("limit", 10)), 10),
            calendar_id=str(params.get("calendar_id", "") or "").strip(),
        )
        report = _format_calendar_events(payload)
        log_event("communications", "calendar_list", report[:2000], metadata={"count": payload.get("count", 0)})
        return report

    if action in {"calendar_book", "calendar_create"}:
        title = str(params.get("title", "") or params.get("summary", "") or "").strip()
        start_iso = str(params.get("start", "") or params.get("start_iso", "") or "").strip()
        end_iso = str(params.get("end", "") or params.get("end_iso", "") or "").strip()
        description = str(params.get("description", "") or params.get("message", "") or "").strip()
        location = str(params.get("location", "") or "").strip()
        attendees = _listify(params.get("attendees", []))
        when_text = str(
            params.get("when", "")
            or params.get("time_text", "")
            or params.get("request", "")
            or ""
        ).strip()
        duration_minutes = _int_value(params.get("duration_minutes", 30), 30)

        if not start_iso or not end_iso:
            planning_input = when_text or description or title
            if not planning_input:
                return "Calendar booking requires either start/end timestamps or a natural-language scheduling request."
            planned = plan_calendar_event_from_text(planning_input, default_duration_minutes=duration_minutes)
            title = title or planned.get("summary", "")
            start_iso = start_iso or planned.get("start_iso", "")
            end_iso = end_iso or planned.get("end_iso", "")
            description = description or planned.get("description", "")
            location = location or planned.get("location", "")
            attendees = attendees or planned.get("attendees", [])

        payload = calendar_create_event(
            summary=title or "AXIOM appointment",
            start_iso=start_iso,
            end_iso=end_iso,
            description=description,
            location=location,
            attendees=attendees,
            calendar_id=str(params.get("calendar_id", "") or "").strip(),
        )
        report = (
            f"Calendar event booked: {payload.get('summary', '')} | "
            f"{payload.get('start', '')} -> {payload.get('end', '')}"
        )
        log_event("communications", "calendar_booked", report[:2000], metadata=payload)
        save_to_nexus(
            "Calendar Booking",
            report,
            kind="communication",
            source="comms_control",
            metadata=payload,
        )
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
