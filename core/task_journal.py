from __future__ import annotations

from memory.runtime_store import get_task_run, list_task_steps, recent_task_events


def build_task_snapshot(task_id: str) -> dict:
    task = get_task_run(task_id)
    if not task:
        return {}

    metadata = dict(task.get("metadata") or {})
    plan_revision = int(metadata.get("plan_revision", 0) or 0)
    steps = list_task_steps(task_id, revision=plan_revision if plan_revision > 0 else None)
    latest_event = next(iter(recent_task_events(task_id=task_id, limit=1)), {})

    active_step = None
    completed_steps = 0
    for step in steps:
        status = str(step.get("status", "") or "").strip().lower()
        if status in {"completed", "skipped"}:
            completed_steps += 1
        if status in {"running", "retrying", "planned"} and active_step is None:
            active_step = step

    if active_step is None and steps:
        for step in steps:
            if str(step.get("status", "") or "").strip().lower() not in {"completed", "failed"}:
                active_step = step
                break

    return {
        "task": task,
        "metadata": metadata,
        "phase": str(metadata.get("phase", "") or "").strip().lower() or str(task.get("status", "") or "").strip().lower(),
        "plan_revision": plan_revision,
        "steps": steps,
        "step_total": len(steps),
        "completed_steps": completed_steps,
        "active_step": active_step or {},
        "latest_event": latest_event or {},
    }


def format_task_snapshot(task_id: str) -> str:
    snapshot = build_task_snapshot(task_id)
    if not snapshot:
        return f"Task [{task_id}] is not recorded in the mission journal."

    task = snapshot["task"]
    lines = [
        f"Task [{task['task_id']}]",
        f"Status: {task['status']}",
        f"Phase: {snapshot['phase'] or 'unknown'}",
        f"Goal: {str(task.get('goal', ''))[:320]}",
    ]

    if snapshot["step_total"]:
        lines.append(
            f"Progress: {snapshot['completed_steps']}/{snapshot['step_total']} planned step(s) completed"
        )

    if snapshot["plan_revision"] > 0:
        lines.append(f"Plan revision: {snapshot['plan_revision']}")

    active_step = snapshot.get("active_step") or {}
    if active_step:
        lines.append(
            "Current step: "
            f"#{active_step.get('step_index')} [{active_step.get('tool', '')}] "
            f"{str(active_step.get('description', '')).strip()[:200]}"
        )

    latest_event = snapshot.get("latest_event") or {}
    if latest_event:
        latest_text = str(latest_event.get("content", "") or "").strip()
        if latest_text:
            lines.append(
                f"Latest event: {latest_event.get('topic', 'event')} | {latest_text[:220]}"
            )

    result_text = str(task.get("result_text", "") or "").strip()
    if result_text and str(task.get("status", "") or "").strip().lower() in {"completed", "failed", "cancelled"}:
        lines.append(f"Result: {result_text[:260]}")

    error_text = str(task.get("error_text", "") or "").strip()
    if error_text:
        lines.append(f"Error: {error_text[:220]}")

    return "\n".join(lines)
