from __future__ import annotations

from typing import Callable

from agent.task_queue import TaskPriority, get_queue


def submit_channel_task(
    goal: str,
    *,
    channel: str,
    scope: str = "",
    origin: str = "",
    priority: TaskPriority = TaskPriority.NORMAL,
    speak: Callable | None = None,
    on_complete: Callable | None = None,
    on_progress: Callable | None = None,
    metadata: dict | None = None,
) -> str:
    payload = {
        "channel": str(channel or "").strip().lower(),
        "scope": str(scope or "").strip(),
        "origin": str(origin or "").strip(),
    }
    if metadata:
        payload.update(metadata)

    return get_queue().submit(
        goal=str(goal or "").strip(),
        priority=priority,
        speak=speak,
        on_complete=on_complete,
        on_progress=on_progress,
        metadata=payload,
    )
