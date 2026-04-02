from __future__ import annotations

import json
import time
import base64
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from core.runtime_config import load_runtime_config
from core.secret_config import get_gemini_api_key


class GeminiNativeError(RuntimeError):
    pass


def _runtime_config() -> dict:
    return load_runtime_config()


def native_runtime_config() -> dict:
    return _runtime_config().get("gemini_native", {}) or {}


def _text_models() -> dict:
    return _runtime_config().get("text_models", {}) or {}


def _require_api_key() -> str:
    api_key = get_gemini_api_key()
    if not api_key:
        raise GeminiNativeError("Gemini API key is missing.")
    return api_key


def get_client(api_key: str = "") -> genai.Client:
    resolved = _non_empty_string(api_key) or _require_api_key()
    return genai.Client(api_key=resolved)


def _non_empty_string(value: Any) -> str:
    return str(value or "").strip()


def _model_from_config(
    key: str,
    *fallbacks: str,
) -> str:
    native = native_runtime_config()
    value = _non_empty_string(native.get(key, ""))
    if value:
        return value
    for fallback in fallbacks:
        value = _non_empty_string(fallback)
        if value:
            return value
    return "gemini-3-flash-preview"


def search_model_name() -> str:
    models = _text_models()
    return _model_from_config(
        "search_model",
        models.get("fast", ""),
        models.get("default", ""),
        "gemini-3-flash-preview",
    )


def planning_model_name() -> str:
    models = _text_models()
    return _model_from_config(
        "planning_model",
        models.get("fast", ""),
        models.get("default", ""),
        "gemini-3.1-flash-lite-preview",
    )


def reflection_model_name() -> str:
    models = _text_models()
    return _model_from_config(
        "reflection_model",
        models.get("default", ""),
        models.get("reasoning", ""),
        "gemini-3-flash-preview",
    )


def router_model_name() -> str:
    models = _text_models()
    return _model_from_config(
        "router_model",
        models.get("fast", ""),
        models.get("default", ""),
        "gemini-3.1-flash-lite-preview",
    )


def url_context_model_name() -> str:
    models = _text_models()
    return _model_from_config(
        "url_context_model",
        models.get("default", ""),
        models.get("fast", ""),
        "gemini-3-flash-preview",
    )


def code_execution_model_name() -> str:
    models = _text_models()
    return _model_from_config(
        "code_execution_model",
        models.get("default", ""),
        models.get("fast", ""),
        "gemini-3-flash-preview",
    )


def maps_model_name() -> str:
    models = _text_models()
    return _model_from_config(
        "maps_model",
        models.get("default", ""),
        models.get("fast", ""),
        "gemini-3-flash-preview",
    )


def file_search_model_name() -> str:
    models = _text_models()
    return _model_from_config(
        "file_search_model",
        models.get("default", ""),
        "gemini-3-flash-preview",
    )


def deep_research_agent_name() -> str:
    native = native_runtime_config()
    configured = _non_empty_string(native.get("deep_research_agent", ""))
    if configured:
        return configured
    return "deep-research-pro-preview-12-2025"


def live_search_enabled() -> bool:
    return bool(native_runtime_config().get("enable_live_google_search", True))


def _flatten_text(response: Any) -> str:
    text = _non_empty_string(getattr(response, "text", ""))
    if text:
        return text

    parts: list[str] = []
    for candidate in list(getattr(response, "candidates", []) or [])[:1]:
        content = getattr(candidate, "content", None)
        for part in list(getattr(content, "parts", []) or []):
            part_text = _non_empty_string(getattr(part, "text", ""))
            if part_text:
                parts.append(part_text)
    return "\n".join(parts).strip()


def _safe_iter(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return list(value)
    except Exception:
        return []


def _build_config(
    *,
    system_instruction: str = "",
    tools: list[Any] | None = None,
    response_mime_type: str = "",
    response_json_schema: dict | None = None,
    tool_config: Any = None,
) -> types.GenerateContentConfig:
    kwargs: dict[str, Any] = {}
    system_text = _non_empty_string(system_instruction)
    if system_text:
        kwargs["system_instruction"] = system_text
    if tools:
        kwargs["tools"] = tools
    if response_mime_type:
        kwargs["response_mime_type"] = response_mime_type
    if response_json_schema:
        kwargs["response_json_schema"] = response_json_schema
    if tool_config is not None:
        kwargs["tool_config"] = tool_config
    return types.GenerateContentConfig(**kwargs)


def _compat_content_part(item: Any) -> Any:
    if item is None:
        return ""
    if isinstance(item, types.Part):
        return item
    if isinstance(item, (bytes, bytearray)):
        return types.Part.from_bytes(data=bytes(item), mime_type="application/octet-stream")
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        text = _non_empty_string(item.get("text", ""))
        if text:
            return text
        mime_type = _non_empty_string(item.get("mime_type", "") or item.get("mimeType", ""))
        data = item.get("data")
        if mime_type and isinstance(data, (bytes, bytearray)):
            return types.Part.from_bytes(data=bytes(data), mime_type=mime_type)
        if mime_type and isinstance(data, str):
            try:
                return types.Part.from_bytes(data=base64.b64decode(data), mime_type=mime_type)
            except Exception:
                pass
    return _non_empty_string(item)


def normalize_contents(contents: Any) -> Any:
    if isinstance(contents, (list, tuple)):
        return [_compat_content_part(item) for item in contents]
    return _compat_content_part(contents)


def generate_response(
    contents: Any,
    *,
    model: str,
    system_instruction: str = "",
    tools: list[Any] | None = None,
    tool_config: Any = None,
    response_mime_type: str = "",
    response_json_schema: dict | None = None,
    api_key: str = "",
) -> Any:
    client = get_client(api_key=api_key)
    return client.models.generate_content(
        model=model,
        contents=normalize_contents(contents),
        config=_build_config(
            system_instruction=system_instruction,
            tools=tools,
            response_mime_type=response_mime_type,
            response_json_schema=response_json_schema,
            tool_config=tool_config,
        ),
    )


def generate_text(
    prompt: str,
    *,
    model: str,
    system_instruction: str = "",
    tools: list[Any] | None = None,
    tool_config: Any = None,
) -> str:
    response = generate_response(
        _non_empty_string(prompt),
        model=model,
        system_instruction=system_instruction,
        tools=tools,
        tool_config=tool_config,
    )
    return _flatten_text(response)


def generate_json(
    prompt: str,
    *,
    model: str,
    schema: dict,
    system_instruction: str = "",
    tools: list[Any] | None = None,
    tool_config: Any = None,
) -> dict:
    response = generate_response(
        _non_empty_string(prompt),
        model=model,
        system_instruction=system_instruction,
        tools=tools,
        response_mime_type="application/json",
        response_json_schema=schema,
        tool_config=tool_config,
    )
    raw = _flatten_text(response)
    if not raw:
        raise GeminiNativeError("Gemini returned an empty JSON response.")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise GeminiNativeError("Gemini returned JSON that was not an object.")
    return payload


def _grounding_chunks_from_response(response: Any) -> tuple[list[dict], list[str]]:
    citations: list[dict] = []
    queries: list[str] = []
    for candidate in list(getattr(response, "candidates", []) or [])[:1]:
        grounding = getattr(candidate, "grounding_metadata", None)
        if grounding is None:
            continue

        for query in _safe_iter(getattr(grounding, "web_search_queries", []) or []):
            query_text = _non_empty_string(query)
            if query_text:
                queries.append(query_text)

        for chunk in _safe_iter(getattr(grounding, "grounding_chunks", []) or []):
            web = getattr(chunk, "web", None)
            maps = getattr(chunk, "maps", None)
            if web is not None:
                title = _non_empty_string(getattr(web, "title", ""))
                uri = _non_empty_string(getattr(web, "uri", ""))
                if title or uri:
                    citations.append({"title": title or uri, "uri": uri})
            elif maps is not None:
                title = _non_empty_string(getattr(maps, "title", ""))
                uri = _non_empty_string(getattr(maps, "uri", ""))
                place_id = _non_empty_string(getattr(maps, "place_id", ""))
                if title or uri or place_id:
                    citations.append(
                        {
                            "title": title or place_id or uri,
                            "uri": uri,
                            "place_id": place_id,
                        }
                    )
    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in citations:
        key = (_non_empty_string(item.get("title", "")), _non_empty_string(item.get("uri", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped, queries


def _format_citations(citations: list[dict], *, label: str = "Sources") -> str:
    if not citations:
        return ""
    lines = [label + ":"]
    for index, item in enumerate(citations, start=1):
        title = _non_empty_string(item.get("title", "")) or f"Source {index}"
        uri = _non_empty_string(item.get("uri", ""))
        if uri:
            lines.append(f"[{index}] {title} - {uri}")
        else:
            lines.append(f"[{index}] {title}")
    return "\n".join(lines)


def google_search(prompt: str, *, model: str = "") -> dict:
    resolved_model = _non_empty_string(model) or search_model_name()
    client = get_client()
    response = client.models.generate_content(
        model=resolved_model,
        contents=_non_empty_string(prompt),
        config=_build_config(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    citations, queries = _grounding_chunks_from_response(response)
    return {
        "model": resolved_model,
        "text": _flatten_text(response),
        "citations": citations,
        "search_queries": queries,
    }


def format_google_search_result(result: dict) -> str:
    body = _non_empty_string(result.get("text", "")) or "No grounded answer was returned."
    extra_sections = []
    citations_block = _format_citations(list(result.get("citations", []) or []))
    if citations_block:
        extra_sections.append(citations_block)
    queries = [query for query in list(result.get("search_queries", []) or []) if _non_empty_string(query)]
    if queries:
        extra_sections.append("Search queries:\n" + "\n".join(f"- {query}" for query in queries))
    if extra_sections:
        return body + "\n\n" + "\n\n".join(extra_sections)
    return body


def _normalize_urls(urls: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if isinstance(urls, str):
        values = [part.strip() for part in urls.splitlines()]
    else:
        values = [str(item).strip() for item in (urls or [])]
    clean: list[str] = []
    seen: set[str] = set()
    max_urls = max(1, int(native_runtime_config().get("url_context_max_urls", 6) or 6))
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        clean.append(value)
        if len(clean) >= max_urls:
            break
    return clean


def url_context(prompt: str, urls: list[str] | tuple[str, ...] | str, *, model: str = "") -> dict:
    url_list = _normalize_urls(urls)
    if not url_list:
        raise GeminiNativeError("URL Context needs at least one URL.")
    resolved_model = _non_empty_string(model) or url_context_model_name()
    joined_urls = "\n".join(f"- {url}" for url in url_list)
    client = get_client()
    response = client.models.generate_content(
        model=resolved_model,
        contents=f"{_non_empty_string(prompt)}\n\nURLs:\n{joined_urls}",
        config=_build_config(
            tools=[types.Tool(url_context=types.UrlContext())],
        ),
    )

    metadata_rows: list[dict] = []
    for candidate in list(getattr(response, "candidates", []) or [])[:1]:
        metadata = getattr(candidate, "url_context_metadata", None)
        for item in _safe_iter(getattr(metadata, "url_metadata", []) or []):
            metadata_rows.append(
                {
                    "retrieved_url": _non_empty_string(getattr(item, "retrieved_url", "")),
                    "status": _non_empty_string(getattr(item, "url_retrieval_status", "")),
                }
            )

    return {
        "model": resolved_model,
        "text": _flatten_text(response),
        "url_metadata": metadata_rows,
        "urls": url_list,
    }


def format_url_context_result(result: dict) -> str:
    body = _non_empty_string(result.get("text", "")) or "No URL-context answer was returned."
    metadata_rows = list(result.get("url_metadata", []) or [])
    if not metadata_rows:
        return body
    lines = ["Retrieved URLs:"]
    for row in metadata_rows:
        url = _non_empty_string(row.get("retrieved_url", ""))
        status = _non_empty_string(row.get("status", "")) or "unknown"
        lines.append(f"- {url or 'unknown url'} | {status}")
    return body + "\n\n" + "\n".join(lines)


def code_execution(prompt: str, *, model: str = "") -> dict:
    resolved_model = _non_empty_string(model) or code_execution_model_name()
    client = get_client()
    response = client.models.generate_content(
        model=resolved_model,
        contents=_non_empty_string(prompt),
        config=_build_config(
            tools=[types.Tool(code_execution=types.ToolCodeExecution())],
        ),
    )
    code_blocks: list[dict] = []
    outputs: list[dict] = []
    for candidate in list(getattr(response, "candidates", []) or [])[:1]:
        content = getattr(candidate, "content", None)
        for part in _safe_iter(getattr(content, "parts", []) or []):
            executable = getattr(part, "executable_code", None)
            if executable is not None:
                code_blocks.append(
                    {
                        "language": _non_empty_string(getattr(executable, "language", "")),
                        "code": _non_empty_string(getattr(executable, "code", "")),
                    }
                )
            execution_result = getattr(part, "code_execution_result", None)
            if execution_result is not None:
                outputs.append(
                    {
                        "outcome": _non_empty_string(getattr(execution_result, "outcome", "")),
                        "output": _non_empty_string(getattr(execution_result, "output", "")),
                    }
                )
    return {
        "model": resolved_model,
        "text": _flatten_text(response),
        "code_blocks": code_blocks,
        "execution_results": outputs,
    }


def format_code_execution_result(result: dict) -> str:
    lines = [_non_empty_string(result.get("text", "")) or "No code-execution answer was returned."]
    for block in list(result.get("code_blocks", []) or []):
        code = _non_empty_string(block.get("code", ""))
        if not code:
            continue
        language = _non_empty_string(block.get("language", "")) or "PYTHON"
        lines.append(f"Generated code ({language}):\n{code}")
    for execution in list(result.get("execution_results", []) or []):
        outcome = _non_empty_string(execution.get("outcome", "")) or "UNKNOWN"
        output = _non_empty_string(execution.get("output", ""))
        lines.append(f"Execution output ({outcome}):\n{output or '[no output]'}")
    return "\n\n".join(lines)


def google_maps(prompt: str, *, latitude: float | None = None, longitude: float | None = None, model: str = "", enable_widget: bool = False) -> dict:
    resolved_model = _non_empty_string(model) or maps_model_name()
    tool_config = None
    if latitude is not None and longitude is not None:
        tool_config = types.ToolConfig(
            retrieval_config=types.RetrievalConfig(
                lat_lng=types.LatLng(latitude=float(latitude), longitude=float(longitude))
            )
        )
    client = get_client()
    response = client.models.generate_content(
        model=resolved_model,
        contents=_non_empty_string(prompt),
        config=_build_config(
            tools=[types.Tool(google_maps=types.GoogleMaps(enable_widget=bool(enable_widget)))],
            tool_config=tool_config,
        ),
    )
    citations, _queries = _grounding_chunks_from_response(response)
    widget_token = ""
    for candidate in list(getattr(response, "candidates", []) or [])[:1]:
        grounding = getattr(candidate, "grounding_metadata", None)
        widget_token = _non_empty_string(getattr(grounding, "google_maps_widget_context_token", ""))
    return {
        "model": resolved_model,
        "text": _flatten_text(response),
        "citations": citations,
        "widget_token": widget_token,
    }


def format_google_maps_result(result: dict) -> str:
    body = _non_empty_string(result.get("text", "")) or "No Google Maps grounded answer was returned."
    citations_block = _format_citations(list(result.get("citations", []) or []), label="Google Maps sources")
    if not citations_block:
        return body
    return body + "\n\n" + citations_block


def deep_research(
    prompt: str,
    *,
    agent: str = "",
    timeout_seconds: int = 900,
    poll_seconds: float = 10.0,
) -> dict:
    resolved_agent = _non_empty_string(agent) or deep_research_agent_name()
    clean_prompt = _non_empty_string(prompt)
    if not clean_prompt:
        raise GeminiNativeError("Deep Research needs a non-empty prompt.")

    client = get_client()
    try:
        interaction = client.interactions.create(
            api_version="v1beta",
            input=clean_prompt,
            agent=resolved_agent,
            background=True,
        )
    except Exception as error:
        raise GeminiNativeError(f"Deep Research could not start: {error}") from error

    interaction_id = _non_empty_string(getattr(interaction, "id", ""))
    if not interaction_id:
        raise GeminiNativeError("Deep Research started without returning an interaction id.")

    deadline = time.time() + max(int(timeout_seconds or 900), 60)
    current = interaction
    status = _non_empty_string(getattr(current, "status", "")).lower()
    while time.time() < deadline:
        if status == "completed":
            break
        if status in {"failed", "cancelled", "canceled", "expired"}:
            break
        time.sleep(max(float(poll_seconds or 10.0), 1.0))
        current = client.interactions.get(interaction_id, api_version="v1beta")
        status = _non_empty_string(getattr(current, "status", "")).lower()

    outputs = list(getattr(current, "outputs", []) or [])
    text = ""
    for item in outputs:
        candidate = _non_empty_string(getattr(item, "text", ""))
        if candidate:
            text = candidate
    error_text = _non_empty_string(getattr(current, "error", ""))

    if status != "completed":
        if time.time() >= deadline and status not in {"failed", "cancelled", "canceled", "expired"}:
            raise GeminiNativeError(
                f"Deep Research timed out after {int(timeout_seconds or 900)} seconds."
            )
        detail = error_text or status or "unknown status"
        raise GeminiNativeError(f"Deep Research failed: {detail}")

    if not text:
        raise GeminiNativeError("Deep Research completed but returned no report text.")

    return {
        "agent": resolved_agent,
        "interaction_id": interaction_id,
        "status": status,
        "text": text,
    }


def format_deep_research_result(result: dict) -> str:
    body = _non_empty_string(result.get("text", "")) or "No Deep Research report was returned."
    interaction_id = _non_empty_string(result.get("interaction_id", ""))
    agent = _non_empty_string(result.get("agent", ""))
    footer = []
    if agent:
        footer.append(f"Deep Research agent: {agent}")
    if interaction_id:
        footer.append(f"Interaction ID: {interaction_id}")
    if not footer:
        return body
    return body + "\n\n" + "\n".join(footer)


def file_search(
    prompt: str,
    files: list[str] | tuple[str, ...] | str,
    *,
    model: str = "",
    display_name: str = "",
    persist_store: bool = False,
    timeout_seconds: int = 180,
) -> dict:
    paths = []
    max_files = max(1, int(native_runtime_config().get("file_search_max_files", 8) or 8))
    for value in _normalize_urls(files):
        path = Path(value)
        if not path.exists() or not path.is_file():
            raise GeminiNativeError(f"File not found for Gemini File Search: {path}")
        paths.append(path)
        if len(paths) >= max_files:
            break
    if not paths:
        raise GeminiNativeError("File Search needs at least one existing file path.")

    client = get_client()
    resolved_model = _non_empty_string(model) or file_search_model_name()
    store_name = _non_empty_string(display_name) or f"axiom-file-search-{int(time.time())}"
    store = client.file_search_stores.create(config={"display_name": store_name})

    try:
        for path in paths:
            operation = client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store.name,
                file=path,
                config={"display_name": path.name},
            )
            deadline = time.time() + max(int(timeout_seconds), 15)
            while not bool(getattr(operation, "done", False)):
                if time.time() >= deadline:
                    raise GeminiNativeError(f"Timed out indexing {path.name} for Gemini File Search.")
                time.sleep(3)
                operation = client.operations.get(operation)

        response = client.models.generate_content(
            model=resolved_model,
            contents=_non_empty_string(prompt),
            config=_build_config(
                tools=[
                    types.Tool(
                        file_search=types.FileSearch(
                            file_search_store_names=[store.name]
                        )
                    )
                ],
            ),
        )
        citations, _queries = _grounding_chunks_from_response(response)
        return {
            "model": resolved_model,
            "text": _flatten_text(response),
            "citations": citations,
            "store_name": store.name,
            "files": [str(path) for path in paths],
        }
    finally:
        if not persist_store:
            try:
                client.file_search_stores.delete(name=store.name)
            except Exception:
                pass


def format_file_search_result(result: dict) -> str:
    body = _non_empty_string(result.get("text", "")) or "No File Search answer was returned."
    citations_block = _format_citations(list(result.get("citations", []) or []), label="File Search sources")
    if not citations_block:
        return body
    return body + "\n\n" + citations_block


def capability_snapshot() -> dict:
    native = native_runtime_config()
    return {
        "enabled": bool(native.get("enabled", True)),
        "live_google_search": live_search_enabled(),
        "search_model": search_model_name(),
        "planning_model": planning_model_name(),
        "reflection_model": reflection_model_name(),
        "router_model": router_model_name(),
        "url_context_model": url_context_model_name(),
        "code_execution_model": code_execution_model_name(),
        "maps_model": maps_model_name(),
        "file_search_model": file_search_model_name(),
        "deep_research_agent": deep_research_agent_name(),
        "file_search_uploads_allowed": bool(native.get("allow_file_search_uploads", False)),
        "file_search_max_files": int(native.get("file_search_max_files", 8) or 8),
        "url_context_max_urls": int(native.get("url_context_max_urls", 6) or 6),
    }


def format_capability_snapshot() -> str:
    caps = capability_snapshot()
    lines = [
        "Gemini native runtime",
        f"Enabled: {'yes' if caps['enabled'] else 'no'}",
        f"Live Google Search enabled: {'yes' if caps['live_google_search'] else 'no'}",
        f"Search model: {caps['search_model']}",
        f"Planning model: {caps['planning_model']}",
        f"Reflection model: {caps['reflection_model']}",
        f"Router model: {caps['router_model']}",
        f"URL Context model: {caps['url_context_model']}",
        f"Code Execution model: {caps['code_execution_model']}",
        f"Google Maps model: {caps['maps_model']}",
        f"File Search model: {caps['file_search_model']}",
        f"Deep Research agent: {caps['deep_research_agent']}",
        f"File Search uploads allowed by default: {'yes' if caps['file_search_uploads_allowed'] else 'no'}",
        f"File Search max files: {caps['file_search_max_files']}",
        f"URL Context max URLs: {caps['url_context_max_urls']}",
    ]
    return "\n".join(lines)
