from core.skill_library import (
    collect_skill_library_status,
    format_skill_entry,
    format_skill_library_status,
    recommend_skill_library,
    resolve_skill_library_sources,
    search_skill_library,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def _format_entries(title: str, rows: list[dict]) -> str:
    if not rows:
        return f"{title}\n- No matching skills were found."
    lines = [title]
    for row in rows:
        lines.append(
            f"- {row['id']} | {row['name']} | {row['source_name']} | "
            f"{(row.get('description', '') or 'no summary')[:140]}"
        )
    return "\n".join(lines)


def skill_library(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()
    limit = int(params.get("limit", 8) or 8)
    source_id = str(params.get("source", "") or "").strip().lower()
    save = bool(params.get("save", False))

    if action == "status":
        report = format_skill_library_status(limit=limit)
        log_event("capabilities", "skill_library_status", report[:2000])
        return report

    if action == "sources":
        sources = resolve_skill_library_sources()
        if not sources:
            return "No external skill libraries were detected."
        lines = ["External skill sources"]
        for source in sources:
            lines.append(
                f"- {source['name']} ({source['id']}) | repo={source['repo_path']} "
                f"| commands={source['commands_count']} hooks={source['hooks_count']} agents={source['agents_count']}"
            )
        return "\n".join(lines)

    if action == "search":
        query = str(params.get("query", "") or "").strip()
        if not query:
            return "Use action='search' with a query."
        rows = search_skill_library(query=query, limit=limit, source_id=source_id)
        report = _format_entries(f"Skill search: {query}", rows)
        log_event("capabilities", "skill_library_search", query[:200], metadata={"matches": len(rows)})
        if save and rows:
            save_to_nexus(
                f"Skill Search: {query}",
                report[:6000],
                kind="capability",
                source="skill_library.search",
            )
        return report

    if action == "recommend":
        task = str(params.get("task", "") or params.get("query", "") or "").strip()
        if not task:
            return "Use action='recommend' with a task or query."
        rows = recommend_skill_library(task=task, limit=limit)
        report = _format_entries(f"Recommended skills for: {task}", rows)
        log_event("capabilities", "skill_library_recommend", task[:200], metadata={"matches": len(rows)})
        if save and rows:
            save_to_nexus(
                f"Skill Recommendations: {task}",
                report[:6000],
                kind="capability",
                source="skill_library.recommend",
            )
        return report

    if action == "read":
        skill_ref = str(params.get("skill", "") or params.get("id", "") or params.get("slug", "") or "").strip()
        if not skill_ref:
            return "Use action='read' with skill=<source:slug> or a skill name."
        report = format_skill_entry(
            skill_ref,
            source_id=source_id,
            content_limit=int(params.get("content_limit", 1400) or 1400),
        )
        log_event("capabilities", "skill_library_read", skill_ref[:200])
        if save and "Skill not found" not in report:
            save_to_nexus(
                f"Skill Read: {skill_ref}",
                report[:6000],
                kind="capability",
                source="skill_library.read",
            )
        return report

    status = collect_skill_library_status(limit=limit)
    return (
        "Unknown action. Use status, sources, search, recommend, or read.\n"
        f"Detected sources: {status['sources_count']}, indexed skills: {status['total_skills']}."
    )
