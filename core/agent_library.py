import json
import re
from pathlib import Path

from core.runtime_config import load_runtime_config
from core.secret_config import get_gemini_api_key, get_secret

try:
    import tomllib
except Exception:  # pragma: no cover - Python <3.11 fallback
    tomllib = None


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
    "paperclip": {
        "name": "Paperclip",
        "config_key": "paperclip_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "paperclip",
        ],
        "special": "paperclip",
    },
    "openfang": {
        "name": "OpenFang",
        "config_key": "openfang_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "openfang",
        ],
        "special": "openfang",
    },
    "openmanus": {
        "name": "OpenManus",
        "config_key": "openmanus_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "OpenManus",
        ],
        "special": "openmanus",
    },
    "symphony": {
        "name": "Symphony",
        "config_key": "symphony_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "symphony",
        ],
        "special": "symphony",
    },
    "lossless_claw": {
        "name": "lossless-claw",
        "config_key": "lossless_claw_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "lossless-claw",
        ],
        "special": "lossless_claw",
    },
    "cashclaw": {
        "name": "CashClaw",
        "config_key": "cashclaw_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "cashclaw",
        ],
        "special": "cashclaw",
    },
    "hyperagents": {
        "name": "HyperAgents",
        "config_key": "hyperagents_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "HyperAgents",
        ],
        "special": "hyperagents",
    },
    "vierisid_jarvis": {
        "name": "Vierisid JARVIS",
        "config_key": "vierisid_jarvis_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "vierisid-jarvis",
        ],
        "special": "vierisid_jarvis",
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
    {
        "triggers": ("workflow", "ticket", "issue", "parallel", "workspace", "handoff", "implementation run"),
        "hints": ("symphony", "orchestrator", "workflow", "ticket", "issue", "workspace"),
    },
    {
        "triggers": ("autonomous", "24/7", "agent os", "browser", "lead", "research", "hands", "operate"),
        "hints": ("openfang", "hand", "browser", "researcher", "lead", "collector", "predictor"),
    },
    {
        "triggers": ("company", "org", "manager", "budget", "heartbeat", "governance", "team"),
        "hints": ("paperclip", "company", "heartbeat", "governance", "budget", "task"),
    },
    {
        "triggers": ("memory", "context", "history", "conversation", "summarize", "recall"),
        "hints": ("lossless", "context", "memory", "conversation", "summary", "lcm"),
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
    elif spec.get("special") == "openfang":
        row["agent_files"] = len(_openfang_hand_cards(repo_path))
    elif spec.get("special") == "cashclaw":
        row["agent_files"] = 3
    elif spec.get("special") == "hyperagents":
        row["agent_files"] = 3
    elif spec.get("special") == "vierisid_jarvis":
        row["agent_files"] = 3
    elif spec.get("special") == "openmanus":
        row["agent_files"] = 4
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
        elif spec.get("special") == "paperclip":
            if not (repo_path / "README.md").exists() or not (repo_path / "skills").exists():
                continue
        elif spec.get("special") == "openfang":
            if not (repo_path / "README.md").exists() or not (repo_path / "crates" / "openfang-hands").exists():
                continue
        elif spec.get("special") == "openmanus":
            if not (repo_path / "README.md").exists() or not (repo_path / "app" / "agent" / "manus.py").exists():
                continue
        elif spec.get("special") == "symphony":
            if not (repo_path / "README.md").exists() or not (repo_path / "SPEC.md").exists():
                continue
        elif spec.get("special") == "lossless_claw":
            if not (repo_path / "README.md").exists():
                continue
        elif spec.get("special") == "cashclaw":
            if not (repo_path / "README.md").exists() or not (repo_path / "src" / "heartbeat.ts").exists():
                continue
        elif spec.get("special") == "hyperagents":
            if not (repo_path / "README.md").exists() or not (repo_path / "meta_agent.py").exists():
                continue
        elif spec.get("special") == "vierisid_jarvis":
            if not (repo_path / "README.md").exists() or not (repo_path / "docs" / "WORKFLOW_AUTOMATION.md").exists():
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
    if special == "paperclip":
        return [
            path
            for path in [
                repo_path / "README.md",
                repo_path / "AGENTS.md",
                repo_path / "skills" / "paperclip" / "SKILL.md",
            ]
            if path.exists()
        ]
    if special == "openfang":
        rows = [path for path in [repo_path / "README.md", repo_path / "Cargo.toml"] if path.exists()]
        for hand_dir, _, _ in _openfang_hand_cards(repo_path):
            for path in [hand_dir / "HAND.toml", hand_dir / "SKILL.md"]:
                if path.exists():
                    rows.append(path)
        return rows
    if special == "openmanus":
        return [
            path
            for path in [
                repo_path / "README.md",
                repo_path / "main.py",
                repo_path / "run_mcp.py",
                repo_path / "run_flow.py",
                repo_path / "app" / "agent" / "manus.py",
                repo_path / "app" / "flow" / "planning.py",
                repo_path / "app" / "agent" / "data_analysis.py",
            ]
            if path.exists()
        ]
    if special == "symphony":
        return [
            path
            for path in [
                repo_path / "README.md",
                repo_path / "SPEC.md",
                repo_path / "elixir" / "AGENTS.md",
            ]
            if path.exists()
        ]
    if special == "lossless_claw":
        return [
            path
            for path in [repo_path / "README.md", repo_path / "AGENTS.md", repo_path / "openclaw.plugin.json"]
            if path.exists()
        ]
    if special == "cashclaw":
        return [
            path
            for path in [
                repo_path / "README.md",
                repo_path / "src" / "heartbeat.ts",
                repo_path / "src" / "loop" / "study.ts",
                repo_path / "src" / "memory" / "search.ts",
            ]
            if path.exists()
        ]
    if special == "hyperagents":
        return [
            path
            for path in [
                repo_path / "README.md",
                repo_path / "meta_agent.py",
                repo_path / "task_agent.py",
                repo_path / "generate_loop.py",
            ]
            if path.exists()
        ]
    if special == "vierisid_jarvis":
        return [
            path
            for path in [
                repo_path / "README.md",
                repo_path / "VISION.md",
                repo_path / "docs" / "WORKFLOW_AUTOMATION.md",
            ]
            if path.exists()
        ]
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


def _read_toml(path: Path) -> dict:
    if tomllib is None or not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _openfang_hand_cards(repo_path: Path) -> list[tuple[Path, str, str]]:
    hands_root = repo_path / "crates" / "openfang-hands" / "bundled"
    if not hands_root.exists():
        return []

    rows = []
    for hand_dir in sorted(path for path in hands_root.iterdir() if path.is_dir()):
        hand_payload = _read_toml(hand_dir / "HAND.toml")
        hand_id = str(hand_payload.get("id", "") or hand_dir.name).strip() or hand_dir.name
        name = str(hand_payload.get("name", "") or hand_dir.name.replace("-", " ").title()).strip()
        rows.append((hand_dir, hand_id, name))
    return rows


def _special_paperclip_entry(source: dict) -> dict:
    repo_path = Path(source["repo_path"])
    skill_path = repo_path / "skills" / "paperclip" / "SKILL.md"
    readme_path = repo_path / "README.md"
    skill_text = _safe_read_text(skill_path, limit=3600)
    readme_text = _safe_read_text(readme_path, limit=2400)
    summary = (
        "Company-scale orchestration operator for managing agent org charts, heartbeats, "
        "budgets, governance, and ticket-based execution."
    )
    return {
        "id": "paperclip:paperclip-control-plane",
        "source_id": "paperclip",
        "source_name": source["name"],
        "repo_path": source["repo_path"],
        "slug": "paperclip-control-plane",
        "name": "Paperclip Control Plane Operator",
        "description": summary,
        "category": "company orchestration",
        "model_hint": "provider-configurable",
        "path": str(skill_path if skill_path.exists() else readme_path),
        "content_preview": (skill_text or readme_text).strip(),
    }


def _special_openfang_entries(source: dict) -> list[dict]:
    repo_path = Path(source["repo_path"])
    entries = []
    for hand_dir, hand_id, name in _openfang_hand_cards(repo_path):
        hand_payload = _read_toml(hand_dir / "HAND.toml")
        description = str(hand_payload.get("description", "") or "").strip()
        category = str(hand_payload.get("category", "") or "autonomous execution").strip()
        skill_path = hand_dir / "SKILL.md"
        preview = _safe_read_text(skill_path if skill_path.exists() else hand_dir / "HAND.toml", limit=2600)
        entries.append(
            {
                "id": f"openfang:{hand_id}",
                "source_id": "openfang",
                "source_name": source["name"],
                "repo_path": source["repo_path"],
                "slug": hand_id,
                "name": name,
                "description": description or f"OpenFang hand for {name}.",
                "category": category,
                "model_hint": str(((hand_payload.get("agent") or {}).get("model")) or "").strip(),
                "path": str(skill_path if skill_path.exists() else hand_dir / "HAND.toml"),
                "content_preview": preview.strip(),
            }
        )
    return entries


def _special_openmanus_entries(source: dict) -> list[dict]:
    repo_path = Path(source["repo_path"])
    readme_text = _safe_read_text(repo_path / "README.md", limit=2600)
    manus_text = _safe_read_text(repo_path / "app" / "agent" / "manus.py", limit=2600)
    mcp_text = _safe_read_text(repo_path / "run_mcp.py", limit=2200)
    flow_text = _safe_read_text(repo_path / "app" / "flow" / "planning.py", limit=2600)
    data_analysis_text = _safe_read_text(repo_path / "app" / "agent" / "data_analysis.py", limit=2200)

    return [
        {
            "id": "openmanus:general-manus-agent",
            "source_id": "openmanus",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "general-manus-agent",
            "name": "OpenManus General Agent",
            "description": (
                "General tool-calling agent that combines Python execution, browser automation, "
                "file editing, ask-human, terminate control, and optional MCP tool injection."
            ),
            "category": "general agent",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "app" / "agent" / "manus.py"),
            "content_preview": (manus_text or readme_text).strip(),
        },
        {
            "id": "openmanus:mcp-agent-runner",
            "source_id": "openmanus",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "mcp-agent-runner",
            "name": "OpenManus MCP Agent Runner",
            "description": (
                "MCP-oriented entrypoint that connects over stdio or SSE and exposes a tool-augmented "
                "agent session against remote or local MCP servers."
            ),
            "category": "mcp orchestration",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "run_mcp.py"),
            "content_preview": (mcp_text or readme_text).strip(),
        },
        {
            "id": "openmanus:planning-flow",
            "source_id": "openmanus",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "planning-flow",
            "name": "OpenManus Planning Flow",
            "description": (
                "Planning/execution flow that creates plan steps, selects executor agents, "
                "marks step status transitions, and summarizes completed plans."
            ),
            "category": "planning and orchestration",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "app" / "flow" / "planning.py"),
            "content_preview": (flow_text or readme_text).strip(),
        },
        {
            "id": "openmanus:data-analysis-agent",
            "source_id": "openmanus",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "data-analysis-agent",
            "name": "OpenManus Data Analysis Agent",
            "description": (
                "Optional specialist role for data analysis and visualization used by the OpenManus "
                "multi-agent planning flow."
            ),
            "category": "data analysis",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "app" / "agent" / "data_analysis.py"),
            "content_preview": (data_analysis_text or readme_text).strip(),
        },
    ]


def _special_symphony_entry(source: dict) -> dict:
    repo_path = Path(source["repo_path"])
    spec_path = repo_path / "SPEC.md"
    agents_path = repo_path / "elixir" / "AGENTS.md"
    spec_text = _safe_read_text(spec_path, limit=3400)
    agents_text = _safe_read_text(agents_path, limit=1800)
    summary = (
        "Issue-driven orchestrator that polls a tracker, creates isolated per-issue workspaces, "
        "and runs coding-agent implementation sessions with workflow policy in-repo."
    )
    return {
        "id": "symphony:symphony-orchestrator",
        "source_id": "symphony",
        "source_name": source["name"],
        "repo_path": source["repo_path"],
        "slug": "symphony-orchestrator",
        "name": "Symphony Orchestrator",
        "description": summary,
        "category": "work orchestration",
        "model_hint": "",
        "path": str(spec_path if spec_path.exists() else agents_path),
        "content_preview": (spec_text or agents_text).strip(),
    }


def _special_lossless_claw_entry(source: dict) -> dict:
    repo_path = Path(source["repo_path"])
    readme_path = repo_path / "README.md"
    readme_text = _safe_read_text(readme_path, limit=3400)
    summary = (
        "Lossless context-management plugin that preserves conversation history in SQLite with "
        "DAG-based summarization and recall tools for long-running agent sessions."
    )
    return {
        "id": "lossless_claw:lossless-context-manager",
        "source_id": "lossless_claw",
        "source_name": source["name"],
        "repo_path": source["repo_path"],
        "slug": "lossless-context-manager",
        "name": "Lossless Context Manager",
        "description": summary,
        "category": "memory and context",
        "model_hint": "",
        "path": str(readme_path),
        "content_preview": readme_text.strip(),
    }


def _special_cashclaw_entries(source: dict) -> list[dict]:
    repo_path = Path(source["repo_path"])
    readme_text = _safe_read_text(repo_path / "README.md", limit=2600)
    heartbeat_text = _safe_read_text(repo_path / "src" / "heartbeat.ts", limit=2600)
    study_text = _safe_read_text(repo_path / "src" / "loop" / "study.ts", limit=2600)
    memory_text = _safe_read_text(repo_path / "src" / "memory" / "search.ts", limit=2200)
    return [
        {
            "id": "cashclaw:heartbeat-operator",
            "source_id": "cashclaw",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "heartbeat-operator",
            "name": "CashClaw Heartbeat Operator",
            "description": (
                "Persistent operator loop that watches for pending work, manages an operator dashboard, "
                "and keeps an always-on heartbeat alive."
            ),
            "category": "continuous operations",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "src" / "heartbeat.ts"),
            "content_preview": (heartbeat_text or readme_text).strip(),
        },
        {
            "id": "cashclaw:self-study-loop",
            "source_id": "cashclaw",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "self-study-loop",
            "name": "CashClaw Self-Study Loop",
            "description": (
                "Self-improvement loop that studies prior tasks, operator feedback, and results to refine future behavior."
            ),
            "category": "self-improvement",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "src" / "loop" / "study.ts"),
            "content_preview": (study_text or readme_text).strip(),
        },
        {
            "id": "cashclaw:memory-search",
            "source_id": "cashclaw",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "memory-search",
            "name": "CashClaw Memory Search",
            "description": (
                "Local memory retrieval layer with ranked search over prior knowledge, notes, and feedback."
            ),
            "category": "memory and retrieval",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "src" / "memory" / "search.ts"),
            "content_preview": (memory_text or readme_text).strip(),
        },
    ]


def _special_hyperagents_entries(source: dict) -> list[dict]:
    repo_path = Path(source["repo_path"])
    readme_text = _safe_read_text(repo_path / "README.md", limit=2600)
    meta_text = _safe_read_text(repo_path / "meta_agent.py", limit=2600)
    task_text = _safe_read_text(repo_path / "task_agent.py", limit=2600)
    loop_text = _safe_read_text(repo_path / "generate_loop.py", limit=2600)
    return [
        {
            "id": "hyperagents:meta-agent",
            "source_id": "hyperagents",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "meta-agent",
            "name": "HyperAgents Meta Agent",
            "description": (
                "Recursive self-improvement supervisor that critiques prior agent generations and proposes the next iteration."
            ),
            "category": "self-improvement",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "meta_agent.py"),
            "content_preview": (meta_text or readme_text).strip(),
        },
        {
            "id": "hyperagents:task-agent",
            "source_id": "hyperagents",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "task-agent",
            "name": "HyperAgents Task Agent",
            "description": (
                "Execution worker that tackles domain tasks, produces artifacts, and feeds results back into the evolution loop."
            ),
            "category": "task execution",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "task_agent.py"),
            "content_preview": (task_text or readme_text).strip(),
        },
        {
            "id": "hyperagents:generate-loop",
            "source_id": "hyperagents",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "generate-loop",
            "name": "HyperAgents Generate Loop",
            "description": (
                "Outer orchestration loop that repeatedly spawns, evaluates, and selects improved agents over multiple generations."
            ),
            "category": "agent orchestration",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "generate_loop.py"),
            "content_preview": (loop_text or readme_text).strip(),
        },
    ]


def _special_vierisid_jarvis_entries(source: dict) -> list[dict]:
    repo_path = Path(source["repo_path"])
    readme_text = _safe_read_text(repo_path / "README.md", limit=2600)
    vision_text = _safe_read_text(repo_path / "VISION.md", limit=2600)
    workflow_text = _safe_read_text(repo_path / "docs" / "WORKFLOW_AUTOMATION.md", limit=2600)
    return [
        {
            "id": "vierisid_jarvis:primary-daemon",
            "source_id": "vierisid_jarvis",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "primary-daemon",
            "name": "JARVIS Primary Daemon",
            "description": (
                "Always-on personal operator daemon with sidecars, memory vault, desktop awareness, and multi-channel control."
            ),
            "category": "personal operator",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "README.md"),
            "content_preview": readme_text.strip(),
        },
        {
            "id": "vierisid_jarvis:workflow-engine",
            "source_id": "vierisid_jarvis",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "workflow-engine",
            "name": "JARVIS Workflow Engine",
            "description": (
                "Natural-language and visual workflow engine with triggers, node graphs, self-healing execution, and background automation."
            ),
            "category": "workflow automation",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "docs" / "WORKFLOW_AUTOMATION.md"),
            "content_preview": (workflow_text or readme_text).strip(),
        },
        {
            "id": "vierisid_jarvis:authority-goals",
            "source_id": "vierisid_jarvis",
            "source_name": source["name"],
            "repo_path": source["repo_path"],
            "slug": "authority-goals",
            "name": "JARVIS Authority and Goals Engine",
            "description": (
                "Authority-gated autonomy layer for approvals, audit trail, long-running goals, and self-improvement loops."
            ),
            "category": "autonomy governance",
            "model_hint": "provider-configurable",
            "path": str(repo_path / "VISION.md"),
            "content_preview": (vision_text or readme_text).strip(),
        },
    ]


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
        if special == "paperclip":
            entries.append(_special_paperclip_entry(source))
            continue
        if special == "openfang":
            entries.extend(_special_openfang_entries(source))
            continue
        if special == "openmanus":
            entries.extend(_special_openmanus_entries(source))
            continue
        if special == "symphony":
            entries.append(_special_symphony_entry(source))
            continue
        if special == "lossless_claw":
            entries.append(_special_lossless_claw_entry(source))
            continue
        if special == "cashclaw":
            entries.extend(_special_cashclaw_entries(source))
            continue
        if special == "hyperagents":
            entries.extend(_special_hyperagents_entries(source))
            continue
        if special == "vierisid_jarvis":
            entries.extend(_special_vierisid_jarvis_entries(source))
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
        if entry["source_id"] == "paperclip" and any(
            word in task_text
            for word in ("company", "org", "manager", "budget", "governance", "heartbeat", "team", "workflow", "ticket")
        ):
            score += 20
        if entry["source_id"] == "openfang" and any(
            word in task_text for word in ("autonomous", "24/7", "browser", "lead", "research", "operate", "telegram")
        ):
            score += 18
        if entry["source_id"] == "openmanus" and any(
            word in task_text
            for word in ("openmanus", "mcp", "sandbox", "browser", "tool calling", "planning flow", "multi-agent", "orchestrate")
        ):
            score += 22
        if entry["source_id"] == "symphony" and any(
            word in task_text for word in ("ticket", "issue", "workflow", "workspace", "parallel", "orchestrate", "handoff")
        ):
            score += 20
        if entry["source_id"] == "lossless_claw" and any(
            word in task_text for word in ("memory", "context", "history", "long conversation", "recall", "summary")
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
    return str((runtime.get("text_models", {}) or {}).get("reasoning", "gemini-3.1-pro-preview") or "gemini-3.1-pro-preview")


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

    api_key = get_gemini_api_key()
    if not api_key:
        return {"ok": False, "message": "Gemini API key is missing, so agent delegation cannot run."}

    from core import gemini_compat as genai

    genai.configure(api_key=api_key)
    resolved_model = str(model_name or _delegate_model_name()).strip() or "gemini-3.1-pro-preview"
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
