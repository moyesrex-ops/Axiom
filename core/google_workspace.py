from __future__ import annotations

import base64
import importlib.util
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

from core import gemini_native as gn
from core.runtime_config import load_runtime_config

READONLY_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

READWRITE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _workspace_config() -> dict:
    communications = load_runtime_config().get("communications", {}) or {}
    return communications.get("google_workspace", {}) or {}


def _workspace_enabled() -> bool:
    return bool(_workspace_config().get("enabled", False))


def _allow_browser_auth() -> bool:
    return bool(_workspace_config().get("allow_browser_auth", True))


def _timezone_name() -> str:
    value = str(_workspace_config().get("timezone", "") or "").strip()
    return value or "UTC"


def _calendar_id() -> str:
    value = str(_workspace_config().get("default_calendar_id", "") or "").strip()
    return value or "primary"


def _client_secret_path() -> Path | None:
    raw = str(_workspace_config().get("client_secret_path", "") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _token_path() -> Path:
    raw = str(_workspace_config().get("token_path", "") or "").strip()
    if raw:
        return Path(raw).expanduser()

    client_secret = _client_secret_path()
    if client_secret:
        return client_secret.with_name("google_workspace_token.json")

    return Path.cwd() / "config" / "google_workspace_token.json"


def _reply_model_name() -> str:
    models = load_runtime_config().get("text_models", {}) or {}
    configured = str(_workspace_config().get("reply_model", "") or "").strip()
    return configured or str(models.get("default", "") or gn.search_model_name())


def _calendar_model_name() -> str:
    models = load_runtime_config().get("text_models", {}) or {}
    configured = str(_workspace_config().get("calendar_model", "") or "").strip()
    return configured or str(models.get("fast", "") or gn.router_model_name())


def _libraries_ready() -> bool:
    return all(
        _has_module(name)
        for name in (
            "googleapiclient.discovery",
            "google.oauth2.credentials",
            "google.auth.transport.requests",
            "google_auth_oauthlib.flow",
        )
    )


def collect_google_workspace_status() -> dict:
    client_secret = _client_secret_path()
    token_path = _token_path()
    gmail_enabled = bool(_workspace_config().get("gmail_enabled", True))
    calendar_enabled = bool(_workspace_config().get("calendar_enabled", True))
    return {
        "enabled": _workspace_enabled(),
        "gmail_enabled": gmail_enabled,
        "calendar_enabled": calendar_enabled,
        "client_secret_path": str(client_secret or ""),
        "client_secret_exists": bool(client_secret and client_secret.exists()),
        "token_path": str(token_path),
        "token_exists": token_path.exists(),
        "libraries_ready": _libraries_ready(),
        "allow_browser_auth": _allow_browser_auth(),
        "timezone": _timezone_name(),
        "default_calendar_id": _calendar_id(),
        "reply_model": _reply_model_name(),
        "calendar_model": _calendar_model_name(),
        "ready": bool(
            _workspace_enabled()
            and _libraries_ready()
            and client_secret
            and client_secret.exists()
        ),
    }


def google_workspace_launch_instructions() -> str:
    status = collect_google_workspace_status()
    return (
        "To enable Google Workspace mail/calendar control:\n"
        "- Create a Google Cloud OAuth desktop client with Gmail and Calendar API enabled.\n"
        "- Put the client secret JSON on disk and set communications.google_workspace.client_secret_path.\n"
        f"- Optional token cache path: communications.google_workspace.token_path (current: {status['token_path']}).\n"
        "- Set communications.google_workspace.enabled=true.\n"
        "- First run will open a local browser OAuth flow if allow_browser_auth=true."
    )


def _resolve_scopes(write_access: bool = False) -> list[str]:
    return list(READWRITE_SCOPES if write_access else READONLY_SCOPES)


def _load_credentials(*, write_access: bool = False):
    if not _libraries_ready():
        raise RuntimeError("Google Workspace client libraries are not installed.")

    if not _workspace_enabled():
        raise RuntimeError("Google Workspace is disabled. " + google_workspace_launch_instructions())

    client_secret = _client_secret_path()
    if not client_secret or not client_secret.exists():
        raise RuntimeError("Google Workspace client secret is missing. " + google_workspace_launch_instructions())

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = _resolve_scopes(write_access=write_access)
    token_path = _token_path()
    credentials = None
    if token_path.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(token_path), scopes)
        except Exception:
            credentials = None

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    elif not credentials or not credentials.valid:
        if not _allow_browser_auth():
            raise RuntimeError(
                "Google Workspace authorization is missing and browser auth is disabled."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), scopes)
        credentials = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def _build_service(api_name: str, version: str, *, write_access: bool = False):
    from googleapiclient.discovery import build

    credentials = _load_credentials(write_access=write_access)
    return build(api_name, version, credentials=credentials, cache_discovery=False)


def _headers_map(headers: list[dict] | None) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for item in headers or []:
        name = str(item.get("name", "") or "").strip().lower()
        if name:
            mapped[name] = str(item.get("value", "") or "").strip()
    return mapped


def _decode_body(payload: dict | None) -> str:
    if not payload:
        return ""

    body = dict(payload.get("body") or {})
    data = str(body.get("data", "") or "").strip()
    mime_type = str(payload.get("mimeType", "") or "").strip().lower()

    if data and mime_type == "text/plain":
        try:
            return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace").strip()
        except Exception:
            return ""

    parts = list(payload.get("parts") or [])
    for preferred in ("text/plain", "text/html"):
        for part in parts:
            if str(part.get("mimeType", "") or "").strip().lower() != preferred:
                continue
            text = _decode_body(part)
            if text:
                return text
    for part in parts:
        text = _decode_body(part)
        if text:
            return text

    if data:
        try:
            return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace").strip()
        except Exception:
            return ""
    return ""


def _message_details(service, message_id: str) -> dict:
    message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    payload = dict(message.get("payload") or {})
    headers = _headers_map(payload.get("headers"))
    return {
        "id": str(message.get("id", "") or ""),
        "thread_id": str(message.get("threadId", "") or ""),
        "label_ids": list(message.get("labelIds") or []),
        "snippet": str(message.get("snippet", "") or "").strip(),
        "subject": headers.get("subject", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "date": headers.get("date", ""),
        "message_id_header": headers.get("message-id", ""),
        "references": headers.get("references", ""),
        "reply_to": headers.get("reply-to", ""),
        "body_text": _decode_body(payload),
    }


def gmail_list_recent_messages(
    *,
    limit: int = 8,
    query: str = "",
    unread_only: bool = False,
) -> dict:
    service = _build_service("gmail", "v1", write_access=False)
    limit = max(1, min(int(limit or 8), 25))
    q = str(query or "").strip()
    if unread_only and "is:unread" not in q:
        q = (q + " is:unread").strip()

    response = service.users().messages().list(
        userId="me",
        maxResults=limit,
        q=q or None,
    ).execute()
    rows = []
    for item in list(response.get("messages") or [])[:limit]:
        rows.append(_message_details(service, str(item.get("id", "") or "")))
    return {"query": q, "count": len(rows), "messages": rows}


def gmail_read_message(message_id: str) -> dict:
    service = _build_service("gmail", "v1", write_access=False)
    message_id = str(message_id or "").strip()
    if not message_id:
        raise RuntimeError("gmail_read_message requires a message_id.")
    return _message_details(service, message_id)


def gmail_generate_reply(message: dict, instruction: str = "") -> str:
    prompt = (
        "Write a natural human email reply for the mailbox owner.\n"
        "Rules:\n"
        "- Sound competent, direct, and human.\n"
        "- Keep it concise unless the context clearly needs more detail.\n"
        "- Do not mention AI or automation.\n"
        "- Output only the email body.\n\n"
        f"From: {str(message.get('from', '') or '').strip()}\n"
        f"Subject: {str(message.get('subject', '') or '').strip()}\n"
        f"Snippet: {str(message.get('snippet', '') or '').strip()}\n"
        f"Message body:\n{str(message.get('body_text', '') or '').strip()[:6000]}\n\n"
        + (f"Extra instruction: {str(instruction or '').strip()}\n\n" if str(instruction or '').strip() else "")
        + "Reply:"
    )
    return gn.generate_text(prompt, model=_reply_model_name()).strip()


def gmail_reply_to_message(
    message_id: str,
    body_text: str,
    *,
    send: bool = False,
) -> dict:
    service = _build_service("gmail", "v1", write_access=True)
    original = _message_details(service, str(message_id or "").strip())
    recipient = original.get("reply_to") or original.get("from") or original.get("to")
    if not recipient:
        raise RuntimeError("Could not determine a reply recipient for that Gmail message.")

    subject = str(original.get("subject", "") or "").strip()
    if subject and not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = subject or "Re:"
    message.set_content(str(body_text or "").strip())

    original_message_id = str(original.get("message_id_header", "") or "").strip()
    if original_message_id:
        message["In-Reply-To"] = original_message_id
        references = " ".join(
            value for value in (str(original.get("references", "") or "").strip(), original_message_id) if value
        ).strip()
        if references:
            message["References"] = references

    payload = {
        "raw": base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8"),
        "threadId": original.get("thread_id", ""),
    }

    if send:
        response = service.users().messages().send(userId="me", body=payload).execute()
        return {
            "mode": "send",
            "id": str(response.get("id", "") or ""),
            "thread_id": str(response.get("threadId", "") or original.get("thread_id", "")),
            "to": recipient,
            "subject": subject,
        }

    response = service.users().drafts().create(
        userId="me",
        body={"message": payload},
    ).execute()
    message_payload = dict(response.get("message") or {})
    return {
        "mode": "draft",
        "draft_id": str(response.get("id", "") or ""),
        "id": str(message_payload.get("id", "") or ""),
        "thread_id": str(message_payload.get("threadId", "") or original.get("thread_id", "")),
        "to": recipient,
        "subject": subject,
    }


def calendar_list_upcoming_events(
    *,
    limit: int = 10,
    calendar_id: str = "",
) -> dict:
    service = _build_service("calendar", "v3", write_access=False)
    limit = max(1, min(int(limit or 10), 25))
    resolved_calendar_id = str(calendar_id or "").strip() or _calendar_id()
    now = datetime.now(ZoneInfo(_timezone_name()))
    response = service.events().list(
        calendarId=resolved_calendar_id,
        timeMin=now.isoformat(),
        maxResults=limit,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    rows = []
    for event in list(response.get("items") or [])[:limit]:
        start = dict(event.get("start") or {})
        end = dict(event.get("end") or {})
        rows.append(
            {
                "id": str(event.get("id", "") or ""),
                "summary": str(event.get("summary", "") or ""),
                "description": str(event.get("description", "") or ""),
                "location": str(event.get("location", "") or ""),
                "start": str(start.get("dateTime", "") or start.get("date", "") or ""),
                "end": str(end.get("dateTime", "") or end.get("date", "") or ""),
                "html_link": str(event.get("htmlLink", "") or ""),
            }
        )
    return {"calendar_id": resolved_calendar_id, "count": len(rows), "events": rows}


def plan_calendar_event_from_text(
    request_text: str,
    *,
    default_duration_minutes: int = 30,
) -> dict:
    now = datetime.now(ZoneInfo(_timezone_name())).isoformat()
    payload = gn.generate_json(
        (
            "Convert this scheduling request into calendar event JSON.\n"
            f"Current time: {now}\n"
            f"Timezone: {_timezone_name()}\n"
            f"Default duration if implied but not stated: {max(5, int(default_duration_minutes or 30))} minutes.\n"
            "Return ISO-8601 dateTime strings with timezone offsets.\n"
            "If a field is unknown, return an empty string or an empty array.\n\n"
            f"Request:\n{str(request_text or '').strip()}"
        ),
        model=_calendar_model_name(),
        schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "start_iso": {"type": "string"},
                "end_iso": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "attendees": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "start_iso", "end_iso", "description", "location", "attendees"],
        },
    )
    if not payload:
        raise RuntimeError("Gemini could not parse that scheduling request into a calendar event.")
    return {
        "summary": str(payload.get("summary", "") or "").strip(),
        "start_iso": str(payload.get("start_iso", "") or "").strip(),
        "end_iso": str(payload.get("end_iso", "") or "").strip(),
        "description": str(payload.get("description", "") or "").strip(),
        "location": str(payload.get("location", "") or "").strip(),
        "attendees": [str(item).strip() for item in list(payload.get("attendees") or []) if str(item).strip()],
    }


def calendar_create_event(
    *,
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
    calendar_id: str = "",
) -> dict:
    service = _build_service("calendar", "v3", write_access=True)
    resolved_calendar_id = str(calendar_id or "").strip() or _calendar_id()
    event = {
        "summary": str(summary or "").strip(),
        "description": str(description or "").strip(),
        "location": str(location or "").strip(),
        "start": {"dateTime": str(start_iso or "").strip(), "timeZone": _timezone_name()},
        "end": {"dateTime": str(end_iso or "").strip(), "timeZone": _timezone_name()},
    }
    attendee_rows = [{"email": value} for value in list(attendees or []) if str(value).strip()]
    if attendee_rows:
        event["attendees"] = attendee_rows

    response = service.events().insert(calendarId=resolved_calendar_id, body=event).execute()
    start_payload = dict(response.get("start") or {})
    end_payload = dict(response.get("end") or {})
    return {
        "id": str(response.get("id", "") or ""),
        "calendar_id": resolved_calendar_id,
        "summary": str(response.get("summary", "") or event["summary"]),
        "start": str(start_payload.get("dateTime", "") or start_payload.get("date", "") or event["start"]["dateTime"]),
        "end": str(end_payload.get("dateTime", "") or end_payload.get("date", "") or event["end"]["dateTime"]),
        "html_link": str(response.get("htmlLink", "") or ""),
    }
