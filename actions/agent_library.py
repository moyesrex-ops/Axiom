from core.agent_library import (
    collect_agent_library_status,
    delegate_agent_library,
    format_agent_delegate_report,
    format_agent_entry,
    format_agent_library_status,
    get_agent_entry,
    recommend_agent_library,
    resolve_agent_library_sources,
    search_agent_library,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def _format_entries(title: str, rows: list[dict]) -> str:
    if not rows:
        return f"{title}\n- No matching agents were found."
    lines = [title]
    for row in rows:
        lines.append(
            f"- {row['id']} | {row['name']} | {row['source_name']} | {row['category']} | "
            f"{(row.get('description', '') or 'no summary')[:140]}"
        )
    return "\n".join(lines)


def agent_library(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()
    limit = int(params.get("limit", 8) or 8)
    source_id = str(params.get("source", "") or "").strip().lower()
    save = bool(params.get("save", False))

    if action == "status":
        report = format_agent_library_status(limit=limit)
        log_event("capabilities", "agent_library_status", report[:2000])
        return report

    if action == "sources":
        sources = resolve_agent_library_sources()
        if not sources:
            return "No external agent libraries were detected."
        lines = ["External agent sources"]
        for source in sources:
            lines.append(
                f"- {source['name']} ({source['id']}) | repo={source['repo_path']} "
                f"| indexed={source.get('agent_files', source.get('indexed_agents', 0))}"
            )
        return "\n".join(lines)

    if action == "search":
        query = str(params.get("query", "") or "").strip()
        if not query:
            return "Use action='search' with a query."
        rows = search_agent_library(query=query, limit=limit, source_id=source_id)
        report = _format_entries(f"Agent search: {query}", rows)
        log_event("capabilities", "agent_library_search", query[:200], metadata={"matches": len(rows)})
        if save and rows:
            save_to_nexus(
                f"Agent Search: {query}",
                report[:6000],
                kind="capability",
                source="agent_library.search",
            )
        return report

    if action == "recommend":
        task = str(params.get("task", "") or params.get("query", "") or "").strip()
        if not task:
            return "Use action='recommend' with a task or query."
        rows = recommend_agent_library(task=task, limit=limit, source_id=source_id)
        report = _format_entries(f"Recommended agents for: {task}", rows)
        log_event("capabilities", "agent_library_recommend", task[:200], metadata={"matches": len(rows)})
        if save and rows:
            save_to_nexus(
                f"Agent Recommendations: {task}",
                report[:6000],
                kind="capability",
                source="agent_library.recommend",
            )
        return report

    if action == "read":
        agent_ref = str(params.get("agent", "") or params.get("id", "") or params.get("slug", "") or "").strip()
        if not agent_ref:
            return "Use action='read' with agent=<source:slug> or an agent name."
        report = format_agent_entry(
            agent_ref,
            source_id=source_id,
            content_limit=int(params.get("content_limit", 1800) or 1800),
        )
        log_event("capabilities", "agent_library_read", agent_ref[:200])
        if save and get_agent_entry(agent_ref, source_id=source_id):
            save_to_nexus(
                f"Agent Read: {agent_ref}",
                report[:6000],
                kind="capability",
                source="agent_library.read",
            )
        return report

    if action == "delegate":
        task = str(params.get("task", "") or params.get("query", "") or "").strip()
        if not task:
            return "Use action='delegate' with a task."
        result = delegate_agent_library(
            task=task,
            query=str(params.get("query", "") or "").strip(),
            agents=params.get("agents"),
            limit=limit,
            source_id=source_id,
            model_name=str(params.get("model", "") or "").strip(),
            context=str(params.get("context", "") or "").strip(),
        )
        report = format_agent_delegate_report(result)
        log_event(
            "swarm",
            "agent_library_delegate",
            task[:500],
            metadata={
                "ok": bool(result.get("ok")),
                "selected": len(result.get("selected_agents", []) or []),
            },
        )
        if save and result.get("ok"):
            save_to_nexus(
                f"Agent Delegation: {task[:80]}",
                report[:6000],
                kind="capability",
                source="agent_library.delegate",
            )
        return report

    status = collect_agent_library_status(limit=limit)
    return (
        "Unknown action. Use status, sources, search, recommend, read, or delegate.\n"
        f"Detected sources: {status['sources_count']}, indexed agents: {status['total_agents']}."
    )
