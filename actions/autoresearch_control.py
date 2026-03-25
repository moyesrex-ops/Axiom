from core.autoresearch_bridge import (
    autoresearch_launch_instructions,
    autoresearch_program_excerpt,
    collect_autoresearch_status,
    configure_autoresearch,
    format_autoresearch_results,
    format_autoresearch_status,
    prepare_autoresearch_repo,
    train_autoresearch_repo,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def autoresearch_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()
    limit = int(params.get("limit", 6) or 6)

    if action == "status":
        report = format_autoresearch_status(limit=limit)
        log_event("integration", "autoresearch_status", report[:2000])
        return report

    if action == "program":
        report = autoresearch_program_excerpt(limit=int(params.get("content_limit", 1800) or 1800))
        log_event("integration", "autoresearch_program", report[:2000])
        return report

    if action == "results":
        report = format_autoresearch_results(limit=limit)
        log_event("integration", "autoresearch_results", report[:2000])
        if bool(params.get("save", False)):
            save_to_nexus(
                "Autoresearch Results",
                report[:6000],
                kind="research",
                source="autoresearch.results",
            )
        return report

    if action == "configure":
        updates = {}
        if "repo_path" in params and params.get("repo_path") not in (None, ""):
            updates["autoresearch_path"] = params.get("repo_path")
        if not updates:
            return format_autoresearch_status(limit=limit)
        cfg = configure_autoresearch(updates)
        message = f"Autoresearch configuration updated: {cfg.get('research_repos', {})}"
        log_event("integration", "autoresearch_configure", message[:2000], metadata=updates)
        save_to_nexus("Autoresearch Config", message[:2000], kind="integration", source="runtime.config")
        return "Autoresearch configuration updated."

    if action == "launch_instructions":
        report = autoresearch_launch_instructions()
        log_event("integration", "autoresearch_launch_instructions", report[:2000])
        return report

    if action == "prepare":
        result = prepare_autoresearch_repo(timeout=int(params.get("timeout", 1800) or 1800))
        message = str(result.get("message", "Autoresearch prepare attempted.")).strip()
        log_event("integration", "autoresearch_prepare", message[:2000], metadata=result)
        lines = [message]
        if result.get("log_path"):
            lines.append(f"Log path: {result['log_path']}")
        if result.get("data_shards") is not None:
            lines.append(f"Data shards: {result['data_shards']}")
        if result.get("tokenizer_ready") is not None:
            lines.append(f"Tokenizer ready: {'yes' if result['tokenizer_ready'] else 'no'}")
        if result.get("output_excerpt"):
            lines.append(f"Output excerpt: {result['output_excerpt']}")
        return "\n".join(lines)

    if action == "train":
        result = train_autoresearch_repo(timeout=int(params.get("timeout", 1800) or 1800))
        message = str(result.get("message", "Autoresearch train attempted.")).strip()
        log_event("integration", "autoresearch_train", message[:2000], metadata=result)
        lines = [message]
        if result.get("log_path"):
            lines.append(f"Log path: {result['log_path']}")
        if result.get("results_count") is not None:
            lines.append(f"Logged experiments: {result['results_count']}")
        if result.get("output_excerpt"):
            lines.append(f"Output excerpt: {result['output_excerpt']}")
        return "\n".join(lines)

    status = collect_autoresearch_status(limit=limit)
    return (
        "Unknown action. Use status, program, results, configure, prepare, train, or launch_instructions.\n"
        f"Repo detected: {'yes' if status['repo_path'] else 'no'}."
    )
