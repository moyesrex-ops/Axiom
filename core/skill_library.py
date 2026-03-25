import re
from pathlib import Path

from core.runtime_config import load_runtime_config


_SOURCE_SPECS = {
    "everything_claude_code": {
        "name": "Everything Claude Code",
        "config_key": "everything_claude_code_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "everything-claude-code",
        ],
    },
    "superpowers": {
        "name": "Superpowers",
        "config_key": "superpowers_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "superpowers",
        ],
    },
    "antigravity": {
        "name": "Antigravity Awesome Skills",
        "config_key": "antigravity_skills_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "antigravity-awesome-skills",
        ],
    },
    "deerflow": {
        "name": "DeerFlow Skills",
        "config_key": "deerflow_path",
        "default_candidates": [
            Path.home() / "deer-flow_upstream",
            Path.home() / "Axiom_research" / "external" / "deer-flow",
        ],
    },
    "impeccable": {
        "name": "Impeccable",
        "config_key": "impeccable_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "impeccable",
        ],
        "skills_subdir": "source/skills",
    },
    "gstack": {
        "name": "gstack",
        "config_key": "gstack_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "gstack",
        ],
        "skills_subdir": ".",
    },
    "cli_anything": {
        "name": "CLI-Anything",
        "config_key": "cli_anything_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "CLI-Anything",
        ],
        "skills_subdir": ".",
    },
    "uncodixfy": {
        "name": "Uncodixfy",
        "config_key": "uncodixfy_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "Uncodixfy",
        ],
        "skills_subdir": ".",
    },
    "paperclip": {
        "name": "Paperclip Skills",
        "config_key": "paperclip_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "paperclip",
        ],
    },
    "openfang_skills": {
        "name": "OpenFang Skills",
        "config_key": "openfang_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "openfang",
        ],
        "skills_subdir": "crates/openfang-skills/bundled",
    },
    "openfang_hands": {
        "name": "OpenFang Hands",
        "config_key": "openfang_path",
        "default_candidates": [
            Path.home() / "Axiom_research" / "external" / "openfang",
        ],
        "skills_subdir": "crates/openfang-hands/bundled",
    },
    "local_skills": {
        "name": "Local Skills",
        "config_key": "local_skills_path",
        "default_candidates": [
            Path.home() / "skills",
        ],
        "skills_subdir": ".",
    },
}

_SKIP_PARTS = {"assets", "docs", "examples", "templates"}
_INDEX_CACHE: dict = {"signature": None, "entries": []}
_CURATED_RECOMMENDATIONS = [
    {
        "triggers": ("debug", "bug", "error", "failing", "traceback"),
        "hints": (
            "systematic-debugging",
            "verification-before-completion",
            "verification-loop",
            "test-fixing",
            "debug",
        ),
    },
    {
        "triggers": ("test", "qa", "verification"),
        "hints": (
            "test-driven-development",
            "tdd-workflow",
            "verification-before-completion",
            "verification-loop",
            "python-testing",
            "testing",
        ),
    },
    {
        "triggers": ("review", "patch", "diff", "pull request", "pr"),
        "hints": (
            "requesting-code-review",
            "receiving-code-review",
            "security-review",
            "differential-review",
            "review",
        ),
    },
    {
        "triggers": ("plan", "branch", "execute", "parallel"),
        "hints": (
            "writing-plans",
            "executing-plans",
            "dispatching-parallel-agents",
            "subagent-driven-development",
            "using-git-worktrees",
            "workflow",
        ),
    },
    {
        "triggers": ("frontend", "ui", "ux", "website", "landing page", "dashboard", "design system", "web page"),
        "hints": (
            "frontend-design",
            "impeccable",
            "uncodix",
            "design-review",
            "design-consultation",
            "typeset",
            "arrange",
            "polish",
            "normalize",
            "critique",
            "react-expert",
            "css-expert",
        ),
    },
    {
        "triggers": ("agent", "workflow", "orchestrate", "ticket", "heartbeat", "company", "parallel", "delegate"),
        "hints": (
            "paperclip",
            "gstack",
            "autoplan",
            "office-hours",
            "plan-",
            "review",
            "openfang",
            "project-manager",
        ),
    },
    {
        "triggers": ("browser", "automation", "control software", "desktop app", "cli", "agent-native"),
        "hints": (
            "cli-anything",
            "browser",
            "openfang",
            "browse",
            "qa",
            "terminal",
        ),
    },
]


def _runtime_skill_config() -> dict:
    return load_runtime_config().get("skill_library", {}) or {}


def _skill_library_enabled() -> bool:
    return bool(_runtime_skill_config().get("enabled", True))


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


def _normalize_slug(parts: list[str]) -> str:
    return "/".join(part for part in parts if part and part != "SKILL.md")


def _title_from_slug(slug: str) -> str:
    tail = slug.split("/")[-1]
    return tail.replace("-", " ").replace("_", " ").strip().title() or slug


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


def _count_dirs(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    count = 0
    for child in path.iterdir():
        if child.is_dir():
            count += 1
    return count


def resolve_skill_library_sources() -> list[dict]:
    runtime = _runtime_skill_config()
    rows: list[dict] = []

    for source_id, spec in _SOURCE_SPECS.items():
        candidates = []
        configured = _path_or_none(runtime.get(spec["config_key"], ""))
        if configured is not None:
            candidates.append(configured)
        candidates.extend(spec["default_candidates"])
        repo_path = _first_existing_path(candidates)
        if repo_path is None:
            continue

        skills_subdir = str(spec.get("skills_subdir", "skills") or "skills").strip()
        skills_dir = repo_path if skills_subdir in ("", ".") else repo_path / skills_subdir
        if not skills_dir.exists():
            continue

        rows.append(
            {
                "id": source_id,
                "name": spec["name"],
                "repo_path": str(repo_path),
                "skills_dir": str(skills_dir),
                "commands_count": _count_dirs(repo_path / "commands"),
                "hooks_count": _count_dirs(repo_path / "hooks"),
                "agents_count": _count_dirs(repo_path / "agents"),
            }
        )

    return rows


def _signature_files(skills_dir: Path) -> list[Path]:
    rows: list[Path] = []
    for skill_path in skills_dir.rglob("SKILL.md"):
        if not _should_index_skill(skill_path, skills_dir):
            continue
        rows.append(skill_path)
        readme_path = skill_path.parent / "README.md"
        if readme_path.exists():
            rows.append(readme_path)
    return sorted(rows)


def _source_signature(sources: list[dict]) -> tuple:
    signature = []
    for source in sources:
        skills_dir = Path(source["skills_dir"])
        file_rows = []
        for path in _signature_files(skills_dir):
            try:
                stat = path.stat()
                file_rows.append((str(path.relative_to(skills_dir)), stat.st_mtime_ns, stat.st_size))
            except Exception:
                file_rows.append((str(path), 0, 0))
        signature.append((source["id"], source["repo_path"], tuple(file_rows)))
    return tuple(signature)


def _should_index_skill(path: Path, skills_dir: Path) -> bool:
    try:
        relative_parts = path.relative_to(skills_dir).parts[:-1]
    except Exception:
        return False

    if not relative_parts:
        return path.name == "SKILL.md"
    return not any(part.lower() in _SKIP_PARTS for part in relative_parts)


def index_skill_library() -> list[dict]:
    if not _skill_library_enabled():
        return []

    sources = resolve_skill_library_sources()
    signature = _source_signature(sources)
    if _INDEX_CACHE["signature"] == signature:
        return list(_INDEX_CACHE["entries"])

    entries: list[dict] = []
    for source in sources:
        skills_dir = Path(source["skills_dir"])
        for skill_path in skills_dir.rglob("SKILL.md"):
            if not _should_index_skill(skill_path, skills_dir):
                continue

            raw = _safe_read_text(skill_path, limit=4000)
            frontmatter, body = _frontmatter_payload(raw)
            relative_parts = list(skill_path.relative_to(skills_dir).parts[:-1])
            slug = _normalize_slug(relative_parts) or skill_path.parent.name.replace("_", "-").replace(" ", "-").lower()
            readme_path = skill_path.parent / "README.md"
            summary = (
                frontmatter.get("description", "").strip()
                or _extract_summary(body)
                or _extract_summary(_safe_read_text(readme_path, limit=1200))
            )

            entries.append(
                {
                    "id": f"{source['id']}:{slug}",
                    "source_id": source["id"],
                    "source_name": source["name"],
                    "repo_path": source["repo_path"],
                    "slug": slug,
                    "name": frontmatter.get("name", "").strip() or _title_from_slug(slug),
                    "description": summary,
                    "path": str(skill_path),
                    "readme_path": str(readme_path) if readme_path.exists() else "",
                    "content_preview": body[:1500].strip(),
                }
            )

    entries.sort(key=lambda item: (item["source_name"], item["slug"]))
    _INDEX_CACHE["signature"] = signature
    _INDEX_CACHE["entries"] = list(entries)
    return entries


def collect_skill_library_status(limit: int = 6) -> dict:
    sources = resolve_skill_library_sources()
    enabled = _skill_library_enabled()
    entries = index_skill_library() if enabled else []
    entry_counts: dict[str, int] = {}
    for item in entries:
        entry_counts[item["source_id"]] = entry_counts.get(item["source_id"], 0) + 1

    rows = []
    for source in sources[: max(int(limit), 1)]:
        rows.append(
            {
                **source,
                "skills_count": entry_counts.get(source["id"], 0),
            }
        )

    return {
        "enabled": enabled,
        "total_skills": len(entries),
        "sources_count": len(sources),
        "sources": rows,
    }


def format_skill_library_status(limit: int = 6) -> str:
    status = collect_skill_library_status(limit=limit)
    lines = [
        "Skill library integration",
        f"Enabled: {'yes' if status['enabled'] else 'no'}",
        f"Sources detected: {status['sources_count']}",
        f"Indexed skills: {status['total_skills']}",
    ]
    for source in status["sources"]:
        lines.append(
            f"- {source['name']}: skills={source['skills_count']} "
            f"commands={source['commands_count']} hooks={source['hooks_count']} "
            f"agents={source['agents_count']} repo={source['repo_path']}"
        )
    return "\n".join(lines)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _entry_search_score(entry: dict, tokens: list[str]) -> int:
    name = str(entry.get("name", "")).lower()
    slug = str(entry.get("slug", "")).lower()
    description = str(entry.get("description", "")).lower()
    preview = str(entry.get("content_preview", "")).lower()

    score = 0
    for token in tokens:
        if token == slug or token == name:
            score += 12
        if token in slug:
            score += 8
        if token in name:
            score += 6
        if token in description:
            score += 4
        if token in preview:
            score += 1
    return score


def search_skill_library(query: str, limit: int = 8, source_id: str = "") -> list[dict]:
    tokens = _tokenize(query)
    if not tokens:
        return []

    rows = []
    for entry in index_skill_library():
        if source_id and entry["source_id"] != source_id:
            continue
        score = _entry_search_score(entry, tokens)
        if score <= 0:
            continue
        rows.append((score, entry))

    rows.sort(key=lambda item: (-item[0], item[1]["source_name"], item[1]["slug"]))
    return [entry for _, entry in rows[: max(int(limit), 1)]]


def recommend_skill_library(task: str, limit: int = 8) -> list[dict]:
    task_text = str(task or "").lower()
    task_tokens = _tokenize(task_text)
    if not task_tokens:
        return []

    rows = []
    for entry in index_skill_library():
        score = _entry_search_score(entry, task_tokens)
        slug = entry["slug"].lower()
        name = entry["name"].lower()
        source_id = entry["source_id"]
        combined = f"{slug} {name}"

        if any(word in task_text for word in ("test", "verify", "qa")) and any(
            hint in f"{slug} {name}" for hint in ("test", "verification", "tdd", "debug")
        ):
            score += 6
        if any(word in task_text for word in ("plan", "branch", "execute")) and any(
            hint in f"{slug} {name}" for hint in ("plan", "workflow", "execution", "parallel", "worktree")
        ):
            score += 6
        if any(word in task_text for word in ("review", "audit", "security")) and any(
            hint in f"{slug} {name}" for hint in ("review", "security", "audit")
        ):
            score += 6
        if any(word in task_text for word in ("debug", "failing", "error", "traceback", "bug")) and any(
            hint in f"{slug} {name}"
            for hint in ("debug", "verification", "review", "test-fixing", "systematic")
        ):
            score += 8
        if any(word in task_text for word in ("patch", "diff", "pull request", "pr")) and any(
            hint in combined for hint in ("review", "patch", "verification")
        ):
            score += 8

        for rule in _CURATED_RECOMMENDATIONS:
            if any(trigger in task_text for trigger in rule["triggers"]) and any(
                hint in combined for hint in rule["hints"]
            ):
                score += 18
                if source_id in {"superpowers", "everything_claude_code"}:
                    score += 35

        if source_id in {"impeccable", "uncodixfy"} and any(
            word in task_text
            for word in ("frontend", "ui", "ux", "website", "landing", "dashboard", "web", "design")
        ):
            score += 26
        if source_id == "gstack" and any(
            word in task_text
            for word in ("plan", "review", "qa", "ship", "orchestrate", "parallel", "workflow", "design")
        ):
            score += 18
        if source_id == "cli_anything" and any(
            word in task_text
            for word in ("cli", "desktop", "software", "browser", "automation", "app", "native")
        ):
            score += 18
        if source_id in {"paperclip", "openfang_skills", "openfang_hands"} and any(
            word in task_text
            for word in ("agent", "autonomous", "team", "company", "research", "browser", "workflow", "operate")
        ):
            score += 14
        if source_id in {"superpowers", "everything_claude_code"} and any(
            word in task_text for word in ("debug", "test", "review", "plan", "execute", "branch", "patch")
        ):
            score += 4
        if source_id == "antigravity":
            score -= 6
        if score <= 0:
            continue
        rows.append((score, entry))

    rows.sort(key=lambda item: (-item[0], len(item[1]["slug"]), item[1]["source_name"], item[1]["slug"]))
    return [entry for _, entry in rows[: max(int(limit), 1)]]


def get_skill_entry(skill_ref: str, source_id: str = "") -> dict | None:
    needle = str(skill_ref or "").strip().lower()
    if not needle:
        return None

    entries = index_skill_library()
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


def format_skill_entry(skill_ref: str, source_id: str = "", content_limit: int = 1400) -> str:
    entry = get_skill_entry(skill_ref, source_id=source_id)
    if entry is None:
        return "Skill not found in the indexed libraries."

    content = _safe_read_text(Path(entry["path"]), limit=max(int(content_limit), 400))
    lines = [
        f"Skill: {entry['name']}",
        f"Source: {entry['source_name']}",
        f"ID: {entry['id']}",
        f"Path: {entry['path']}",
    ]
    if entry["description"]:
        lines.append(f"Summary: {entry['description']}")
    if entry["readme_path"]:
        lines.append(f"README: {entry['readme_path']}")
    if content:
        lines.append("")
        lines.append(content.strip())
    return "\n".join(lines).strip()
