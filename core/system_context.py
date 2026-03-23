import json
import locale
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


_CACHE_TTL_SECONDS = 1200
_CACHE_AT = 0.0
_CACHE_DATA: dict = {}
_TIMEZONE_HINTS = {
    "America/Regina": {"city": "Regina", "region": "Saskatchewan", "country": "Canada"},
    "Canada Central Standard Time": {"region": "Saskatchewan", "country": "Canada"},
}


def _format_utc_offset(dt: datetime) -> str:
    offset = dt.strftime("%z") or ""
    if len(offset) == 5:
        return f"{offset[:3]}:{offset[3:]}"
    return offset or "unknown"


def _best_locale() -> str:
    for getter in (locale.getlocale, locale.getdefaultlocale):
        try:
            lang, encoding = getter()
            if lang and encoding:
                return f"{lang}.{encoding}"
            if lang:
                return str(lang)
        except Exception:
            continue
    return ""


def _run_powershell_json(command: str) -> dict:
    if not sys.platform.startswith("win"):
        return {}

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except Exception:
        return {}

    raw = str(result.stdout or "").strip()
    if not raw:
        return {}

    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _public_ip_context(timeout: float = 1.0) -> dict:
    if requests is None:
        return {}

    sources = (
        (
            "ipwho.is",
            "https://ipwho.is/",
            lambda payload: {
                "ip": payload.get("ip", ""),
                "city": payload.get("city", ""),
                "region": payload.get("region", ""),
                "country": payload.get("country", ""),
                "country_code": payload.get("country_code", ""),
                "timezone_name": payload.get("timezone", {}).get("id", ""),
                "latitude": payload.get("latitude"),
                "longitude": payload.get("longitude"),
            }
            if payload.get("success") is True
            else {},
        ),
        (
            "ipapi.co",
            "https://ipapi.co/json/",
            lambda payload: {
                "ip": payload.get("ip", ""),
                "city": payload.get("city", ""),
                "region": payload.get("region", ""),
                "country": payload.get("country_name", ""),
                "country_code": payload.get("country_code", ""),
                "timezone_name": payload.get("timezone", ""),
                "latitude": payload.get("latitude"),
                "longitude": payload.get("longitude"),
            },
        ),
    )

    for source_name, url, parser in sources:
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            parsed = parser(payload)
            if parsed:
                parsed["public_location_source"] = source_name
                return parsed
        except Exception:
            continue
    return {}


def _apply_timezone_location_hint(data: dict) -> None:
    for key in (data.get("timezone_name", ""), data.get("timezone_id", "")):
        hint = _TIMEZONE_HINTS.get(str(key or "").strip())
        if not hint:
            continue
        for field, value in hint.items():
            if not data.get(field):
                data[field] = value
        return


def collect_system_context(force_refresh: bool = False) -> dict:
    global _CACHE_AT, _CACHE_DATA

    now = time.time()
    if not force_refresh and _CACHE_DATA and (now - _CACHE_AT) < _CACHE_TTL_SECONDS:
        return dict(_CACHE_DATA)

    local_now = datetime.now().astimezone()
    data = {
        "local_time_iso": local_now.isoformat(timespec="seconds"),
        "date_label": local_now.strftime("%A, %B %d, %Y"),
        "time_label": local_now.strftime("%I:%M %p").lstrip("0"),
        "timezone_name": local_now.tzname() or "",
        "timezone_id": "",
        "timezone_display": "",
        "utc_offset": _format_utc_offset(local_now),
        "locale": _best_locale(),
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "username": os.getenv("USERNAME") or os.getenv("USER") or "",
        "ip": "",
        "city": "",
        "region": "",
        "country": "",
        "country_code": "",
        "latitude": None,
        "longitude": None,
        "public_location_source": "",
    }

    if sys.platform.startswith("win"):
        timezone_info = _run_powershell_json(
            "Get-TimeZone | Select-Object Id,DisplayName | ConvertTo-Json -Compress"
        )
        if timezone_info:
            data["timezone_id"] = str(timezone_info.get("Id", "") or "").strip()
            data["timezone_display"] = str(timezone_info.get("DisplayName", "") or "").strip()

        culture_info = _run_powershell_json(
            "Get-Culture | Select-Object Name,DisplayName | ConvertTo-Json -Compress"
        )
        if culture_info and not data["locale"]:
            data["locale"] = str(culture_info.get("Name", "") or "").strip()

    geo = _public_ip_context()
    if geo:
        data.update({k: v for k, v in geo.items() if v not in ("", None)})
        if geo.get("timezone_name"):
            data["timezone_name"] = str(geo["timezone_name"])
    else:
        _apply_timezone_location_hint(data)

    _CACHE_AT = now
    _CACHE_DATA = dict(data)
    return dict(data)


def format_system_context(context: dict | None = None) -> str:
    ctx = context or collect_system_context()
    location_bits = [ctx.get("city", ""), ctx.get("region", ""), ctx.get("country", "")]
    location_text = ", ".join(bit for bit in location_bits if bit) or "unavailable"

    lines = [
        "AXIOM system context",
        f"Local date: {ctx.get('date_label', 'unknown')}",
        f"Local time: {ctx.get('time_label', 'unknown')}",
        f"Timezone: {ctx.get('timezone_name', '') or ctx.get('timezone_id', '') or 'unknown'}",
        f"UTC offset: {ctx.get('utc_offset', 'unknown')}",
        f"Locale: {ctx.get('locale', 'unknown') or 'unknown'}",
        f"Best-effort location: {location_text}",
    ]

    if ctx.get("public_location_source"):
        lines.append(f"Location source: {ctx['public_location_source']}")
    if ctx.get("ip"):
        lines.append(f"Public IP: {ctx['ip']}")

    return "\n".join(lines)


def format_prompt_system_context(context: dict | None = None) -> str:
    ctx = context or collect_system_context()
    timezone_name = ctx.get("timezone_name", "") or ctx.get("timezone_id", "") or "unknown"

    lines = [
        "[SYSTEM CONTEXT]",
        f"Default local timezone: {timezone_name} (UTC{ctx.get('utc_offset', 'unknown')})",
    ]

    location_bits = [ctx.get("city", ""), ctx.get("region", ""), ctx.get("country", "")]
    location_text = ", ".join(bit for bit in location_bits if bit)
    if location_text:
        lines.append(f"Best-effort location hint: {location_text}")

    if ctx.get("locale"):
        lines.append(f"Locale hint: {ctx['locale']}")

    lines.append("Use this as the user's default local context unless they explicitly override it.")
    return "\n".join(lines)
