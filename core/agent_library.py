import json
import re
from pathlib import Path

from core.runtime_config import load_runtime_config
from core.secret_config import get_secret


_SOURCE_SPECS = {
    "wshobson_agents": {
        "name": "WS Hobson Agents",
        "config_key": "wshobson_agents_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "wshobson-agents",
        ],
        "glob": "plugins/*/agents/*.md",
    },
    "awesome_subagents": {
        "name": "Claude Code Subagents",
        "config_key": "awesome_subagents_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "awesome-claude-code-subagents",
        ],
        "glob": "categories/**/*.md",
    },
    "dexter": {
        "name": "Dexter",
        "config_key": "dexter_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "dexter",
        ],
        "special": "dexter",
    },
    "pentagi": {
        "name": "PentAGI",
        "config_key": "pentagi_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "pentagi",
        ],
        "special": "pentagi",
    },
    "tradingagents": {
        "name": "TradingAgents",
        "config_key": "tradingagents_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "TradingAgents",
        ],
        "special": "tradingagents",
    },
}

_INDEX_CACHE: dict = {"signature": None, "entries": []}
_CURATED_RECOMMENDATIONS = [
    {
        "triggers": ("frontend", "ui", "website", "landing page", "react", "design system"),
        "hints": ("frontend", "ui", "ux", "design", "react", "web", "css", "accessibility"),
    },
    {
        "triggers": ("backend", "api", "database", "service", "worker", "microservice"),
        "hints": ("backend", "api", "database", "sql", "microservice", "server", "architecture"),
    },
    {
        "triggers": ("video", "editing", "studio", "motion", "cinematic", "youtube"),
        "hints": ("video", "motion", "editor", "storyboard", "creative", "studio", "cinematic"),
    },
    {
        "triggers": ("security", "pentest", "red team", "exploit", "vulnerability", "audit"),
        "hints": ("security", "pentest", "red-team", "infra", "audit", "vulnerability", "compliance"),
    },
    {
        "triggers": ("research", "analysis", "report", "deep dive", "market", "finance"),
        "hints": ("research", "analysis", "market", "finance", "report", "strategy", "dexter", "tradingagents"),
    },
    {
        "triggers": ("devops", "infra", "deploy", "docker", "kubernetes", "cloud"),
        "hints": ("devops", "infra", "cloud", "kubernetes", "docker", "platform", "sre"),
    },
    {
        "triggers": ("trading", "ticker", "portfolio", "equity", "stock", "risk", "bullish", "bearish"),
        "hints": ("trading", "market", "portfolio", "risk", "analyst", "bull", "bear", "tradingagents"),
    },
]

_TRADINGAGENTS_ROLE_SUMMARIES = {
    "fundamentals_analyst": "Evaluates company financials, intrinsic value, and balance-sheet strength.",
    "market_analyst": "Studies price action, indicators, and market structure.",
    "news_analyst": "Tracks company and macro news flow for market-moving events.",
    "social_media_analyst": "Extracts market sentiment from public discussions and social channels.",
    "bull_researcher": "Argues the bullish case in the investment debate loop.",
    "bear_researcher": "Argues the bearish case in the investment debate loop.",
    "aggressive_debator": "Advocates the aggressive risk posture in the risk debate loop.",
    "conservative_debator": "Advocates the conservative risk posture in the risk debate loop.",
    "neutral_debator": "Acts as a balancing voice in the risk debate loop.",
    "trader": "Synthesizes analyst and debate outputs into a concrete trade decision.",
    "portfolio_manager": "Approves or rejects the proposed trade at the portfolio layer.",
    "research_manager": "Coordinates research flows across the analyst and debate teams.",
}


def _runtime_agent_config() -> dict:
    return load_runtime_config().get("agent_library", {}) or {}


def _agent_library_enabled() -> bool:
    return bool(_runtime_agent_config().get("enabled", True))


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


def _safe_read_text(path: Path, limit: int | None = None) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return text if limit is None else text[:limit]
    except Exception:
        return ""


def _frontmatter_payload(text: str) -> tuple[dict, str]:
    raw = str(text or "")
    if not raw.startswith("---\n"):
        return {}, raw

    end = raw.find("\n---\n", 4)
    if end < 0:
        return {}, raw

    header = raw[4:end]
    body = raw[end + 5 :]
    payload: dict = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip("'\"")
        if key:
            payload[key] = value
    return payload, body


def _extract_summary(body: str) -> str:
    in_code = False
    for raw_line in str(body or "").splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line or line.startswith("#") or line.startswith("- "):
            continue
        return re.sub(r"\s+", " ", line)
    return ""


def _title_from_slug(slug: str) -> str:
    tail = slug.split("/")[-1]
    return tail.replace("-", " ").replace("_", " ").strip().title() or slug


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _normalize_slug(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root).with_suffix("")
        return "/".join(relative.parts)
    except Exception:
        return path.stem


def _count_entries(repo_path: Path, glob_pattern: str) -> int:
    try:
        return sum(1 for item in repo_path.glob(glob_pattern) if item.is_file())
    except Exception:
        return 0


def _agent_source_row(source_id: str, spec: dict, repo_path: Path) -> dict:
    row = {
        "id": source_id,
        "name": spec["name"],
        "repo_path": str(repo_path),
        "special": spec.get("special", ""),
        "glob": spec.get("glob", ""),
    }
    if spec.get("special") == "tradingagents":
        row["agent_files"] = len(_tradingagents_role_cards(repo_path))
    elif spec.get("special"):
        row["agent_files"] = 1
    elif spec.get("glob"):
        row["agent_files"] = _count_entries(repo_path, spec["glob"])
    return row


def resolve_agent_library_sources() -> list[dict]:
    runtime = _runtime_agent_config()
    full_runtime = load_runtime_config()
    rows: list[dict] = []

    for source_id, spec in _SOURCE_SPECS.items():
        candidates = []
        configured = _path_or_none(runtime.get(spec["config_key"], ""))
        if configured is not None:
            candidates.append(configured)
        if source_id == "tradingagents":
            configured_sidecar = _path_or_none((full_runtime.get("tradingagents", {}) or {}).get("repo_path", ""))
            if configured_sidecar is not None:
                candidates.append(configured_sidecar)
        candidates.extend(spec["default_candidates"])
        repo_path = _first_existing_path(candidates)
        if repo_path is None:
            continue

        if spec.get("special") == "dexter":
            if not (repo_path / "README.md").exists():
                continue
        elif spec.get("special") == "pentagi":
            if not (repo_path / "README.md").exists():
                continue
        elif spec.get("special") == "tradingagents":
            if not (repo_path / "README.md").exists() or not (repo_path / "tradingagents").exists():
                continue
        elif not any(repo_path.glob(spec["glob"])):
            continue

        rows.append(_agent_source_row(source_id, spec, repo_path))

    return rows


def _signature_files_for_source(source: dict) -> list[Path]:
    repo_path = Path(source["repo_path"])
    special = str(source.get("special", "") or "").strip()
    if special == "dexter":
        return [path for path in [repo_path / "AGENTS.md", repo_path / "README.md"] if path.exists()]
    if special == "pentagi":
        return [path for path in [repo_path / "README.md", repo_path / "LICENSE"] if path.exists()]
    if special == "tradingagents":
        rows = [path for path in [repo_path / "README.md", repo_path / "pyproject.toml"] if path.exists()]
        rows.extend(path for path, _, _, _ in _tradingagents_role_cards(repo_path))
        return rows
    glob_pattern = str(source.get("glob", "") or "").strip()
    return sorted(path for path in repo_path.glob(glob_pattern) if path.is_file())


def _source_signature(sources: list[dict]) -> tuple:
    signature = []
    for source in sources:
        file_rows = []
        for path in _signature_files_for_source(source):
            try:
                stat = path.stat()
                file_rows.append((str(path), stat.st_mtime_ns, stat.st_size))
            except Exception:
                file_rows.append((str(path), 0, 0))
        signature.append((source["id"], source["repo_path"], tuple(file_rows)))
    return tuple(signature)


def _source_category(source_id: str, path: Path, repo_path: Path) -> str:
    if source_id == "wshobson_agents":
        parts = path.relative_to(repo_path).parts
        if len(parts) >= 3:
            return parts[1].replace("-", " ")
    if source_id == "awesome_subagents":
        parts = path.relative_to(repo_path).parts
        if len(parts) >= 2:
            return parts[1].replace("-", " ")
    if source_id == "dexter":
        return "financial research"
    if source_id == "pentagi":
        return "security"
    if source_id == "tradingagents":
        return "market analysis"
    return "general"


def _special_dexter_entry(source: dict) -> dict:
    repo_path = Path(source["repo_path"])
    guide_path = repo_path / "AGENTS.md"
    readme_path = repo_path / "README.md"
    guide_text = _safe_read_text(guide_path, limit=3200)
    readme_text = _safe_read_text(readme_path, limit=2200)
    summary = (
        "Deep financial research operator with browser, web search, finance tools, "
        "scratchpad memory, and SKILL.md workflows."
    )
    return {
        "id": "dexter:dexter-financial-researcher",
        "source_id": "dexter",
        "source_name": source["name"],
        "repo_path": source["repo_path"],
        "slug": "dexter-financial-researcher",
        "name": "Dexter Financial Researcher",
        "description": summary,
        "category": "financial research",
        "model_hint": "provider-configurable",
        "path": str(guide_path if guide_path.exists() else readme_path),
        "content_preview": (guide_text or readme_text).strip(),
    }


def _special_pentagi_entry(source: dict) -> dict:
    repo_path = Path(source["repo_path"])
    readme_path = repo_path / "README.md"
    readme_text = _safe_read_text(readme_path, limit=3400)
    summary = (
        "Security and penetration-testing specialist catalog entry. Upstream README "
        "currently reports a temporary source-code withdrawal during a license audit."
    )
    return {
        "id": "pentagi:pentagi-security-operator",
        "source_id": "pentagi",
        "source_name": source["name"],
        "repo_path": source["repo_path"],
        "slug": "pentagi-security-operator",
        "name": "PentAGI Security Operator",
        "description": summary,
        "category": "security",
        "model_hint": "provider-configurable",
        "path": str(readme_path),
        "content_preview": readme_text.strip(),
    }


def _tradingagents_role_cards(repo_path: Path) -> list[tuple[Path, str, str, str]]:
    agents_root = repo_path / "tradingagents" / "agents"
    if not agents_root.exists():
        return []

    category_map = {
        "analysts": "market analysis",
        "researchers": "investment research",
        "risk_mgmt": "risk management",
        "trader": "trading execution",
        "managers": "portfolio management",
    }

    rows = []
    for path in sorted(agents_root.rglob("*.py")):
        if not path.is_file() or path.name == "__init__.py" or "utils" in path.parts:
            continue
        stem = path.stem
        category = category_map.get(path.parent.name, "market analysis")
        summary = _TRADINGAGENTS_ROLE_SUMMARIES.get(
            stem,
            f"TradingAgents role card derived from {stem.replace('_', ' ')}.",
        )
        slug = f"{path.parent.name}/{stem}"
        name = stem.replace("_", " ").strip().title()
        rows.append((path, slug, name, category + "||" + summary))
    return rows


def _special_tradingagents_entries(source: dict) -> list[dict]:
    repo_path = Path(source["repo_path"])
    entries = []
    for path, slug, name, packed in _tradingagents_role_cards(repo_path):
        category, summary = packed.split("||", 1)
        content = _safe_read_text(path, limit=2600)
        entries.append(
            {
                "id": f"tradingagents:{slug}",
                "source_id": "tradingagents",
                "source_name": source["name"],
                "repo_path": source["repo_path"],
                "slug": slug,
                "name": name,
                "description": summary,
                "category": category,
                "model_hint": "provider-configurable",
                "path": str(path),
                "content_preview": content.strip(),
            }
        )
    return entries


def index_agent_library() -> list[dict]:
    if not _agent_library_enabled():
        return []

    sources = resolve_agent_library_sources()
    signature = _source_signature(sources)
    if _INDEX_CACHE["signature"] == signature:
        return list(_INDEX_CACHE["entries"])

    entries: list[dict] = []
    for source in sources:
        source_id = source["id"]
        source_name = source["name"]
        repo_path = Path(source["repo_path"])
        special = str(source.get("special", "") or "").strip()

        if special == "dexter":
            entries.append(_special_dexter_entry(source))
            continue
        if special == "pentagi":
            entries.append(_special_pentagi_entry(source))
            continue
        if special == "tradingagents":
            entries.extend(_special_tradingagents_entries(source))
            continue

        for path in repo_path.glob(source["glob"]):
            if not path.is_file():
                continue
            raw = _safe_read_text(path, limit=5000)
            frontmatter, body = _frontmatter_payload(raw)
            slug = _normalize_slug(path, repo_path)
            description = frontmatter.get("description", "").strip() or _extract_summary(body)
            entries.append(
                {
                    "id": f"{source_id}:{slug}",
                    "source_id": source_id,
                    "source_name": source_name,
                    "repo_path": source["repo_path"],
                    "slug": slug,
                    "name": frontmatter.get("name", "").strip() or _title_from_slug(path.stem),
                    "description": description,
                    "category": _source_category(source_id, path, repo_path),
                    "model_hint": frontmatter.get("model", "").strip(),
                    "path": str(path),
                    "content_preview": body[:2400].strip(),
                }
            )

    entries.sort(key=lambda item: (item["source_name"], item["category"], item["name"]))
    _INDEX_CACHE["signature"] = signature
    _INDEX_CACHE["entries"] = list(entries)
    return entries


def collect_agent_library_status(limit: int = 6) -> dict:
    sources = resolve_agent_library_sources()
    enabled = _agent_library_enabled()
    entries = index_agent_library() if enabled else []
    entry_counts: dict[str, int] = {}
    for item in entries:
        entry_counts[item["source_id"]] = entry_counts.get(item["source_id"], 0) + 1

    rows = []
    for source in sources[: max(int(limit), 1)]:
        rows.append(
            {
                **source,
                "indexed_agents": entry_counts.get(source["id"], 0),
            }
        )

    return {
        "enabled": enabled,
        "total_agents": len(entries),
        "sources_count": len(sources),
        "sources": rows,
    }


def format_agent_library_status(limit: int = 6) -> str:
    status = collect_agent_library_status(limit=limit)
    lines = [
        "Agent library integration",
        f"Enabled: {'yes' if status['enabled'] else 'no'}",
        f"Sources detected: {status['sources_count']}",
        f"Indexed agents: {status['total_agents']}",
    ]
    for source in status["sources"]:
        lines.append(
            f"- {source['name']} ({source['id']}) | indexed={source['indexed_agents']} "
            f"| repo={source['repo_path']}"
        )
    return "\n".join(lines)


def _entry_search_score(entry: dict, tokens: list[str]) -> int:
    searchable = " ".join(
        [
            str(entry.get("name", "")).lower(),
            str(entry.get("slug", "")).lower(),
            str(entry.get("description", "")).lower(),
            str(entry.get("category", "")).lower(),
            str(entry.get("content_preview", "")).lower(),
            str(entry.get("source_name", "")).lower(),
        ]
    )
    score = 0
    for token in tokens:
        if token in searchable:
            score += 2
        if token in str(entry.get("name", "")).lower():
            score += 5
        if token in str(entry.get("slug", "")).lower():
            score += 4
        if token in str(entry.get("category", "")).lower():
            score += 5
    return score


def search_agent_library(query: str, limit: int = 8, source_id: str = "") -> list[dict]:
    tokens = _tokenize(query)
    if not tokens:
        return []

    rows = []
    for entry in index_agent_library():
        if source_id and entry["source_id"] != source_id:
            continue
        score = _entry_search_score(entry, tokens)
        if score <= 0:
            continue
        rows.append((score, entry))

    rows.sort(key=lambda item: (-item[0], item[1]["source_name"], item[1]["name"]))
    return [entry for _, entry in rows[: max(int(limit), 1)]]


def recommend_agent_library(task: str, limit: int = 8, source_id: str = "") -> list[dict]:
    task_text = str(task or "").lower()
    tokens = _tokenize(task_text)
    if not tokens:
        return []

    rows = []
    for entry in index_agent_library():
        if source_id and entry["source_id"] != source_id:
            continue

        score = _entry_search_score(entry, tokens)
        combined = " ".join(
            [
                entry.get("name", "").lower(),
                entry.get("slug", "").lower(),
                entry.get("category", "").lower(),
                entry.get("description", "").lower(),
            ]
        )

        for rule in _CURATED_RECOMMENDATIONS:
            if any(trigger in task_text for trigger in rule["triggers"]) and any(
                hint in combined for hint in rule["hints"]
            ):
                score += 16

        if entry["source_id"] == "dexter" and any(
            word in task_text for word in ("finance", "market", "equity", "stocks", "trading")
        ):
            score += 22
        if entry["source_id"] == "pentagi" and any(
            word in task_text for word in ("security", "pentest", "red team", "vulnerability", "exploit")
        ):
            score += 18

        if score <= 0:
            continue
        rows.append((score, entry))

    rows.sort(key=lambda item: (-item[0], item[1]["source_name"], item[1]["name"]))
    return [entry for _, entry in rows[: max(int(limit), 1)]]


def get_agent_entry(agent_ref: str, source_id: str = "") -> dict | None:
    needle = str(agent_ref or "").strip().lower()
    if not needle:
        return None

    entries = index_agent_library()
    for entry in entries:
        if source_id and entry["source_id"] != source_id:
            continue
        if needle == entry["id"].lower():
            return entry

    for entry in entries:
        if source_id and entry["source_id"] != source_id:
            continue
        if needle in {
            entry["slug"].lower(),
            entry["name"].lower(),
            entry["slug"].split("/")[-1].lower(),
        }:
            return entry
    return None


def format_agent_entry(agent_ref: str, source_id: str = "", content_limit: int = 1800) -> str:
    entry = get_agent_entry(agent_ref, source_id=source_id)
    if entry is None:
        return "Agent not found in the indexed library."

    content = _safe_read_text(Path(entry["path"]), limit=max(int(content_limit), 500))
    lines = [
        f"Agent: {entry['name']}",
        f"Source: {entry['source_name']}",
        f"ID: {entry['id']}",
        f"Category: {entry['category']}",
        f"Path: {entry['path']}",
    ]
    if entry["model_hint"]:
        lines.append(f"Model hint: {entry['model_hint']}")
    if entry["description"]:
        lines.append(f"Summary: {entry['description']}")
    if content:
        lines.append("")
        lines.append(content.strip())
    return "\n".join(lines).strip()


def _normalize_agent_refs(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _delegate_model_name() -> str:
    runtime = load_runtime_config()
    configured = str(_runtime_agent_config().get("delegate_model", "") or "").strip()
    if configured:
        return configured
    return str((runtime.get("text_models", {}) or {}).get("reasoning", "gemini-2.5-pro") or "gemini-2.5-pro")


def delegate_agent_library(
    task: str,
    query: str = "",
    agents=None,
    limit: int = 3,
    source_id: str = "",
    model_name: str = "",
    context: str = "",
) -> dict:
    task = str(task or "").strip()
    if not task:
        return {"ok": False, "message": "Please provide a task for agent delegation."}

    requested_agents = _normalize_agent_refs(agents)
    selected: list[dict] = []
    if requested_agents:
        for agent_ref in requested_agents:
            entry = get_agent_entry(agent_ref, source_id=source_id)
            if entry is not None:
                selected.append(entry)
    else:
        search_query = query or task
        selected = recommend_agent_library(task=search_query, limit=limit, source_id=source_id)
        if not selected:
            selected = search_agent_library(query=search_query, limit=limit, source_id=source_id)

    if not selected:
        return {"ok": False, "message": "No suitable agents were found for delegation."}

    api_key = get_secret("gemini_api_key", ["GEMINI_API_KEY"])
    if not api_key:
        return {"ok": False, "message": "Gemini API key is missing, so agent delegation cannot run."}

    import google.generativeai as genai

    genai.configure(api_key=api_key)
    resolved_model = str(model_name or _delegate_model_name()).strip() or "gemini-2.5-pro"
    model = genai.GenerativeModel(resolved_model)

    agent_reports = []
    for entry in selected[: max(1, min(int(limit), 5))]:
        prompt = f"""You are operating inside AXIOM as a delegated specialist.
Use the imported agent card below as your operating profile. Stay concrete and execution-focused.

AGENT NAME: {entry['name']}
SOURCE: {entry['source_name']}
CATEGORY: {entry['category']}
SUMMARY: {entry['description'] or 'No summary provided.'}

AGENT CARD EXCERPT:
{entry['content_preview'][:2600]}

TASK:
{task}

CONTEXT:
{context or 'No extra context provided.'}

Return:
1. Role-specific plan
2. Risks or blockers
3. Concrete output or handoff
4. One-line verdict"""
        try:
            report = model.generate_content(prompt).text.strip()
        except Exception as exc:
            report = f"Agent run failed: {exc}"
        agent_reports.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "source_name": entry["source_name"],
                "category": entry["category"],
                "report": report,
            }
        )

    synthesis_prompt = f"""You are AXIOM supervising delegated specialists.
Task: {task}
Context: {context or 'No extra context provided.'}

AGENT REPORTS:
{json.dumps(agent_reports, ensure_ascii=False, indent=2)}

Produce:
1. Best execution order
2. Points of agreement
3. Points of conflict
4. Final supervised recommendation
5. Immediate next actions"""
    try:
        supervisor_report = model.generate_content(synthesis_prompt).text.strip()
    except Exception as exc:
        supervisor_report = f"Supervisor synthesis failed: {exc}"

    return {
        "ok": True,
        "task": task,
        "model": resolved_model,
        "selected_agents": [
            {
                "id": item["id"],
                "name": item["name"],
                "source_name": item["source_name"],
                "category": item["category"],
            }
            for item in selected[: max(1, min(int(limit), 5))]
        ],
        "agent_reports": agent_reports,
        "supervisor_report": supervisor_report,
    }


def format_agent_delegate_report(result: dict) -> str:
    if not result.get("ok"):
        return str(result.get("message", "Agent delegation failed."))

    lines = [
        f"Delegated task: {result['task']}",
        f"Model: {result['model']}",
        "Selected agents:",
    ]
    for row in result.get("selected_agents", []):
        lines.append(
            f"- {row['name']} | {row['source_name']} | {row['category']} | {row['id']}"
        )
    for row in result.get("agent_reports", []):
        lines.append("")
        lines.append(f"== {row['name'].upper()} ==")
        lines.append(row.get("report", "").strip() or "No report returned.")
    lines.append("")
    lines.append("== AXIOM SUPERVISOR ==")
    lines.append(str(result.get("supervisor_report", "") or "No supervisor report returned.").strip())
    return "\n".join(lines).strip()
