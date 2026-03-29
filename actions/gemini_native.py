from __future__ import annotations

from core import gemini_native as gn
from memory.runtime_store import log_event


def _string_list(value) -> list[str]:
    if isinstance(value, str):
        parts = [part.strip() for part in value.replace(";", "\n").splitlines()]
        return [part for part in parts if part]
    return [str(item).strip() for item in (value or []) if str(item).strip()]


def gemini_native(parameters: dict = None, player=None, speak=None) -> str:
    params = dict(parameters or {})
    action = str(params.get("action", "status") or "status").strip().lower()
    model = str(params.get("model", "") or "").strip()

    try:
        if action in {"status", "info", "capabilities"}:
            report = gn.format_capability_snapshot()
            log_event("gemini_native", "status", report[:2000])
            return report

        if action in {"search", "google_search"}:
            query = str(params.get("query", "") or params.get("prompt", "") or "").strip()
            if not query:
                return "Provide query=<text> for Gemini native search."
            result = gn.google_search(query, model=model)
            report = gn.format_google_search_result(result)
            log_event("gemini_native", "search", query[:300], metadata={"model": result["model"]})
            return report

        if action == "url_context":
            prompt = str(params.get("prompt", "") or params.get("query", "") or "").strip()
            urls = _string_list(params.get("urls", []) or params.get("url", ""))
            if not prompt:
                return "Provide prompt=<question> for Gemini URL Context."
            if not urls:
                return "Provide urls=[...] for Gemini URL Context."
            result = gn.url_context(prompt, urls, model=model)
            report = gn.format_url_context_result(result)
            log_event(
                "gemini_native",
                "url_context",
                prompt[:300],
                metadata={"model": result["model"], "url_count": len(result["urls"])},
            )
            return report

        if action in {"code_execution", "code"}:
            prompt = str(params.get("prompt", "") or params.get("query", "") or "").strip()
            if not prompt:
                return "Provide prompt=<question> for Gemini Code Execution."
            result = gn.code_execution(prompt, model=model)
            report = gn.format_code_execution_result(result)
            log_event("gemini_native", "code_execution", prompt[:300], metadata={"model": result["model"]})
            return report

        if action in {"maps", "google_maps"}:
            prompt = str(params.get("prompt", "") or params.get("query", "") or "").strip()
            if not prompt:
                return "Provide prompt=<question> for Gemini Google Maps grounding."
            latitude = params.get("latitude", params.get("lat"))
            longitude = params.get("longitude", params.get("lng"))
            try:
                latitude = float(latitude) if latitude not in (None, "") else None
                longitude = float(longitude) if longitude not in (None, "") else None
            except Exception:
                return "Latitude and longitude must be numeric when provided."
            result = gn.google_maps(
                prompt,
                latitude=latitude,
                longitude=longitude,
                model=model,
                enable_widget=bool(params.get("enable_widget", False)),
            )
            report = gn.format_google_maps_result(result)
            log_event("gemini_native", "google_maps", prompt[:300], metadata={"model": result["model"]})
            return report

        if action == "file_search":
            prompt = str(params.get("prompt", "") or params.get("query", "") or "").strip()
            files = _string_list(params.get("files", []) or params.get("paths", []))
            if not prompt:
                return "Provide prompt=<question> for Gemini File Search."
            if not files:
                return "Provide files=[...] for Gemini File Search."
            uploads_allowed = bool(gn.native_runtime_config().get("allow_file_search_uploads", False))
            confirm_upload = bool(params.get("confirm_upload", False))
            if not uploads_allowed and not confirm_upload:
                return (
                    "Gemini File Search uploads local files to Google's File Search service. "
                    "Retry with confirm_upload=true or enable gemini_native.allow_file_search_uploads in runtime config."
                )
            result = gn.file_search(
                prompt,
                files,
                model=model,
                display_name=str(params.get("display_name", "") or "").strip(),
                persist_store=bool(params.get("persist_store", False)),
                timeout_seconds=int(params.get("timeout", 180) or 180),
            )
            report = gn.format_file_search_result(result)
            log_event(
                "gemini_native",
                "file_search",
                prompt[:300],
                metadata={"model": result["model"], "file_count": len(result["files"])},
            )
            return report

        return (
            "Unknown action. Use status, search, url_context, code_execution, maps, or file_search."
        )

    except gn.GeminiNativeError as error:
        return str(error)
    except Exception as error:
        log_event("gemini_native", "error", str(error)[:500], metadata={"action": action})
        return f"Gemini native action failed: {error}"
