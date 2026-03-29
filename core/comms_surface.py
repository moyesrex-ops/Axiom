import importlib.util
import os
import smtplib
from email.message import EmailMessage

from core.runtime_config import load_runtime_config
from core.secret_config import get_secret


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _communications_config() -> dict:
    return load_runtime_config().get("communications", {}) or {}


def _email_config() -> dict:
    return _communications_config().get("email", {}) or {}


def _telephony_config() -> dict:
    return _communications_config().get("telephony", {}) or {}


def _env_or_config(env_name: str, config_value: str = "") -> str:
    value = str(os.getenv(env_name, "") or "").strip()
    if value:
        return value
    return str(config_value or "").strip()


def _email_runtime_settings() -> dict:
    cfg = _email_config()
    host = _env_or_config("AXIOM_SMTP_HOST", cfg.get("smtp_host", ""))
    if not host:
        host = _env_or_config("SMTP_HOST", cfg.get("smtp_host", ""))
    username = get_secret("smtp_username", ["AXIOM_SMTP_USERNAME", "SMTP_USERNAME"])
    password = get_secret("smtp_password", ["AXIOM_SMTP_PASSWORD", "SMTP_PASSWORD"])
    from_address = (
        get_secret("smtp_from_address", ["AXIOM_SMTP_FROM", "SMTP_FROM_ADDRESS"])
        or str(cfg.get("from_address", "") or "").strip()
        or username
    )
    try:
        port = int(_env_or_config("AXIOM_SMTP_PORT", str(cfg.get("smtp_port", 587) or 587)))
    except Exception:
        port = 587
    use_tls = bool(cfg.get("use_tls", True))
    enabled = bool(cfg.get("enabled", False))
    return {
        "enabled": enabled,
        "host": host,
        "port": port,
        "username": username,
        "password_present": bool(password),
        "password": password,
        "from_address": from_address,
        "use_tls": use_tls,
        "ready": bool(enabled and host and username and password and from_address),
    }


def _telephony_runtime_settings() -> dict:
    cfg = _telephony_config()
    provider = str(cfg.get("provider", "twilio") or "twilio").strip().lower()
    account_sid = get_secret("twilio_account_sid", ["AXIOM_TWILIO_ACCOUNT_SID", "TWILIO_ACCOUNT_SID"])
    auth_token = get_secret("twilio_auth_token", ["AXIOM_TWILIO_AUTH_TOKEN", "TWILIO_AUTH_TOKEN"])
    from_number = (
        get_secret("twilio_from_number", ["AXIOM_TWILIO_FROM_NUMBER", "TWILIO_FROM_NUMBER"])
        or str(cfg.get("from_number", "") or "").strip()
    )
    default_to_number = (
        get_secret("default_to_number", ["AXIOM_DEFAULT_TO_NUMBER"])
        or str(cfg.get("default_to_number", "") or "").strip()
    )
    twilio_installed = _has_module("twilio")
    enabled = bool(cfg.get("enabled", False))
    ready = bool(enabled and provider == "twilio" and twilio_installed and account_sid and auth_token and from_number)
    return {
        "enabled": enabled,
        "provider": provider,
        "account_sid_present": bool(account_sid),
        "auth_token_present": bool(auth_token),
        "from_number": from_number,
        "default_to_number": default_to_number,
        "sdk_installed": twilio_installed,
        "sms_ready": ready,
        "call_ready": ready,
        "account_sid": account_sid,
        "auth_token": auth_token,
    }


def collect_comms_status() -> dict:
    runtime = load_runtime_config()
    telegram_cfg = runtime.get("channels", {}).get("telegram", {}) or {}
    telegram_token = get_secret("telegram_bot_token", ["AXIOM_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN"])
    desktop_apps_cfg = _communications_config().get("desktop_apps", {}) or {}
    email = _email_runtime_settings()
    telephony = _telephony_runtime_settings()
    return {
        "telegram_bridge_enabled": bool(telegram_cfg.get("enabled", False)),
        "telegram_token_present": bool(telegram_token),
        "telegram_allowed_chat_count": len(telegram_cfg.get("allowed_chat_ids", []) or []),
        "desktop_app_automation_enabled": bool(desktop_apps_cfg.get("enabled", True)),
        "desktop_messaging_ready": bool(desktop_apps_cfg.get("enabled", True) and _has_module("pyautogui")),
        "email": email,
        "telephony": telephony,
    }


def format_comms_status() -> str:
    status = collect_comms_status()
    email = status["email"]
    telephony = status["telephony"]
    lines = [
        "[COMMUNICATION SURFACE]",
        f"- Telegram bridge: {'enabled' if status['telegram_bridge_enabled'] else 'disabled'} | token={'yes' if status['telegram_token_present'] else 'no'} | allowed_chats={status['telegram_allowed_chat_count']}",
        f"- Desktop messaging automation: {'ready' if status['desktop_messaging_ready'] else 'not ready'}",
        (
            f"- Email channel: {'ready' if email['ready'] else 'not ready'} | "
            f"enabled={'yes' if email['enabled'] else 'no'} | host={email['host'] or 'not configured'} | "
            f"from={email['from_address'] or 'not configured'}"
        ),
        (
            f"- Telephony channel: provider={telephony['provider']} | "
            f"sdk={'yes' if telephony['sdk_installed'] else 'no'} | "
            f"sms_ready={'yes' if telephony['sms_ready'] else 'no'} | "
            f"call_ready={'yes' if telephony['call_ready'] else 'no'} | "
            f"from={telephony['from_number'] or 'not configured'}"
        ),
        "- Use comms_control for unified send/email/sms/call routing.",
    ]
    return "\n".join(lines)


def email_launch_instructions() -> str:
    return (
        "To enable SMTP email, configure runtime communications.email plus these secrets as needed:\n"
        "- AXIOM_SMTP_HOST or communications.email.smtp_host\n"
        "- AXIOM_SMTP_USERNAME / SMTP_USERNAME\n"
        "- AXIOM_SMTP_PASSWORD / SMTP_PASSWORD\n"
        "- AXIOM_SMTP_FROM / SMTP_FROM_ADDRESS or communications.email.from_address"
    )


def telephony_launch_instructions() -> str:
    return (
        "To enable SMS/calls via Twilio, install the twilio package and configure:\n"
        "- AXIOM_TWILIO_ACCOUNT_SID / TWILIO_ACCOUNT_SID\n"
        "- AXIOM_TWILIO_AUTH_TOKEN / TWILIO_AUTH_TOKEN\n"
        "- AXIOM_TWILIO_FROM_NUMBER / TWILIO_FROM_NUMBER\n"
        "- communications.telephony.enabled=true"
    )


def send_email_via_smtp(to_address: str, subject: str, body: str) -> str:
    settings = _email_runtime_settings()
    if not settings["ready"]:
        return "Email channel is not ready. " + email_launch_instructions()
    recipient = str(to_address or "").strip()
    if not recipient:
        return "Email send requires a destination address."

    message = EmailMessage()
    message["From"] = settings["from_address"]
    message["To"] = recipient
    message["Subject"] = str(subject or "AXIOM Message").strip() or "AXIOM Message"
    message.set_content(str(body or "").strip())

    if settings["use_tls"]:
        with smtplib.SMTP(settings["host"], settings["port"], timeout=20) as server:
            server.starttls()
            server.login(settings["username"], settings["password"])
            server.send_message(message)
    else:
        with smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=20) as server:
            server.login(settings["username"], settings["password"])
            server.send_message(message)
    return f"Email sent to {recipient} via SMTP."


def send_sms_via_twilio(to_number: str, body: str) -> str:
    settings = _telephony_runtime_settings()
    if not settings["sms_ready"]:
        return "SMS channel is not ready. " + telephony_launch_instructions()
    recipient = str(to_number or "").strip() or settings["default_to_number"]
    if not recipient:
        return "SMS send requires a destination number."

    from twilio.rest import Client

    client = Client(settings["account_sid"], settings["auth_token"])
    message = client.messages.create(
        body=str(body or "").strip(),
        from_=settings["from_number"],
        to=recipient,
    )
    return f"SMS sent to {recipient}. Twilio SID: {message.sid}"


def place_call_via_twilio(to_number: str, message_text: str) -> str:
    settings = _telephony_runtime_settings()
    if not settings["call_ready"]:
        return "Call channel is not ready. " + telephony_launch_instructions()
    recipient = str(to_number or "").strip() or settings["default_to_number"]
    if not recipient:
        return "Call action requires a destination number."

    from twilio.rest import Client
    from twilio.twiml.voice_response import VoiceResponse

    response = VoiceResponse()
    response.say(str(message_text or "AXIOM is calling."), voice="alice")
    client = Client(settings["account_sid"], settings["auth_token"])
    call = client.calls.create(
        twiml=str(response),
        from_=settings["from_number"],
        to=recipient,
    )
    return f"Call placed to {recipient}. Twilio SID: {call.sid}"
