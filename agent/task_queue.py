import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Any

from memory.runtime_store import append_task_event, log_event, upsert_channel_state, upsert_task_run


class TaskStatus(Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


class TaskPriority(Enum):
    LOW    = 3
    NORMAL = 2
    HIGH   = 1


@dataclass(order=True)
class Task:
    priority:    int
    created_at:  float = field(compare=False)
    task_id:     str   = field(compare=False)
    goal:        str   = field(compare=False)
    status:      TaskStatus = field(compare=False, default=TaskStatus.PENDING)
    result:      Any        = field(compare=False, default=None)
    error:       str        = field(compare=False, default="")
    speak:       Any        = field(compare=False, default=None)
    on_complete: Any        = field(compare=False, default=None)
    on_progress: Any        = field(compare=False, default=None)
    metadata:    dict       = field(compare=False, default_factory=dict)
    cancel_flag: threading.Event = field(compare=False, default_factory=threading.Event)


class TaskQueue:
    def __init__(self, max_concurrent: int = 1):
        self._queue:        list[Task]       = []
        self._lock:         threading.Lock   = threading.Lock()
        self._condition:    threading.Condition = threading.Condition(self._lock)
        self._tasks:        dict[str, Task]  = {}
        self._running:      bool             = False
        self._worker_thread: threading.Thread | None = None
        self._max_concurrent = max_concurrent
        self._active_count   = 0
        self._executor       = None

    def _get_executor(self):
        if self._executor is None:
            from agent.executor import AgentExecutor
            self._executor = AgentExecutor()
        return self._executor

    def start(self) -> None:
        if self._running:
            return
        self._running      = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="AxiomTaskQueue"
        )
        self._worker_thread.start()
        print("[TaskQueue] Started")
        log_event("task_queue", "started", "Task queue worker started.")

    def stop(self) -> None:
        self._running = False
        with self._condition:
            self._condition.notify_all()
        print("[TaskQueue] Stopped")
        log_event("task_queue", "stopped", "Task queue worker stopped.")

    def _snapshot(self, task: Task, metadata: dict | None = None) -> None:
        snapshot_metadata = {"priority": task.priority, **(task.metadata or {})}
        if metadata:
            snapshot_metadata.update(metadata)
        upsert_task_run(
            task_id=task.task_id,
            goal=task.goal,
            status=task.status.value,
            result_text="" if task.result is None else str(task.result),
            error_text=task.error,
            metadata=snapshot_metadata,
        )
        channel = str(snapshot_metadata.get("channel", "") or "").strip().lower()
        scope = str(snapshot_metadata.get("scope", "") or "").strip()
        if channel:
            last_result = None
            active_task_id = None
            if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                active_task_id = task.task_id
            else:
                active_task_id = ""
                last_result = str(task.result or task.error or task.status.value)[:4000]

            upsert_channel_state(
                channel=channel,
                scope=scope,
                active_task_id=active_task_id,
                last_task_id=task.task_id if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING) else None,
                last_goal=task.goal,
                last_result=last_result,
                metadata={
                    "task_id": task.task_id,
                    "task_status": task.status.value,
                    "origin": str(snapshot_metadata.get("origin", "") or ""),
                },
            )
            if channel in {"voice", "telegram"}:
                upsert_channel_state(
                    channel="operator",
                    scope="shared",
                    active_task_id=active_task_id,
                    last_task_id=task.task_id if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING) else None,
                    last_goal=task.goal,
                    last_result=last_result,
                    metadata={
                        "task_id": task.task_id,
                        "task_status": task.status.value,
                        "origin": str(snapshot_metadata.get("origin", "") or ""),
                        "last_channel": channel,
                        "last_scope": scope,
                    },
                )

    def submit(
        self,
        goal:        str,
        priority:    TaskPriority = TaskPriority.NORMAL,
        speak:       Callable | None = None,
        on_complete: Callable | None = None,
        on_progress: Callable | None = None,
        metadata:    dict | None = None,
    ) -> str:

        task_id = str(uuid.uuid4())[:8]
        task    = Task(
            priority    = priority.value,
            created_at  = time.time(),
            task_id     = task_id,
            goal        = goal,
            speak       = speak,
            on_complete = on_complete,
            on_progress = on_progress,
            metadata    = dict(metadata or {}),
        )

        with self._condition:
            self._queue.append(task)
            self._queue.sort(key=lambda t: (t.priority, t.created_at))
            self._tasks[task_id] = task
            self._condition.notify()

        print(f"[TaskQueue] Task queued: [{task_id}] {goal[:60]}")
        self._snapshot(task)
        append_task_event(
            task_id,
            "queued",
            "Task queued.",
            phase="queued",
            metadata=task.metadata,
        )
        log_event("task_queue", "queued", f"[{task_id}] {goal[:300]}")
        return task_id

    def cancel(self, task_id: str) -> bool:

        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return False

            task.cancel_flag.set()
            task.status = TaskStatus.CANCELLED
            print(f"[TaskQueue] Task cancelled: [{task_id}]")
            self._snapshot(task)
            append_task_event(
                task_id,
                "cancelled",
                "Task cancelled before completion.",
                phase="cancelled",
                metadata=task.metadata,
            )
            log_event("task_queue", "cancelled", f"[{task_id}] {task.goal[:300]}")
            return True

    def get_status(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return {
                "task_id": task.task_id,
                "goal":    task.goal,
                "status":  task.status.value,
                "result":  task.result,
                "error":   task.error,
            }

    def get_all_statuses(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "task_id": t.task_id,
                    "goal":    t.goal[:50],
                    "status":  t.status.value,
                }
                for t in self._tasks.values()
            ]

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._queue if t.status == TaskStatus.PENDING)

    def _worker_loop(self) -> None:
        while self._running:
            task = None

            with self._condition:
                while self._running and not self._next_task():
                    self._condition.wait(timeout=1.0)
                task = self._next_task()
                if task:
                    task.status = TaskStatus.RUNNING
                    self._active_count += 1
                    try:
                        self._queue.remove(task)
                    except ValueError:
                        pass
                    self._snapshot(task)
                    append_task_event(
                        task.task_id,
                        "running",
                        "Task execution started.",
                        phase="executing",
                        metadata=task.metadata,
                    )
                    log_event("task_queue", "running", f"[{task.task_id}] {task.goal[:300]}")

            if task:
                threading.Thread(
                    target=self._run_task,
                    args=(task,),
                    daemon=True,
                    name=f"AxiomTask-{task.task_id}"
                ).start()

    def _next_task(self) -> Task | None:
        if self._active_count >= self._max_concurrent:
            return None
        for task in self._queue:
            if task.status == TaskStatus.PENDING and not task.cancel_flag.is_set():
                return task
        return None

    def _run_task(self, task: Task) -> None:
        print(f"[TaskQueue] Running: [{task.task_id}] {task.goal[:60]}")
        try:
            executor = self._get_executor()

            def _progress_callback(event: dict | None) -> None:
                payload = dict(event or {})
                if not payload:
                    return

                with self._lock:
                    phase = str(payload.get("phase", "") or "").strip().lower()
                    if phase:
                        task.metadata["phase"] = phase
                    if payload.get("plan_revision") not in (None, ""):
                        task.metadata["plan_revision"] = int(payload.get("plan_revision") or 0)
                    if payload.get("step_index") not in (None, ""):
                        task.metadata["current_step_index"] = int(payload.get("step_index") or 0)
                    if payload.get("step_total") not in (None, ""):
                        task.metadata["step_total"] = int(payload.get("step_total") or 0)
                    if payload.get("tool"):
                        task.metadata["current_tool"] = str(payload.get("tool") or "")
                    if payload.get("topic"):
                        task.metadata["last_progress_topic"] = str(payload.get("topic") or "")
                    if payload.get("message"):
                        task.metadata["last_progress"] = str(payload.get("message") or "")[:500]
                    task.metadata["last_progress_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    self._snapshot(task)

                if task.on_progress:
                    try:
                        task.on_progress(task.task_id, dict(payload))
                    except Exception:
                        pass

            result   = executor.execute(
                goal        = task.goal,
                speak       = task.speak,
                cancel_flag = task.cancel_flag,
                task_id     = task.task_id,
                task_metadata = dict(task.metadata),
                progress_callback = _progress_callback,
            )

            with self._lock:
                if task.cancel_flag.is_set():
                    task.status = TaskStatus.CANCELLED
                elif _looks_like_failed_result(result):
                    task.status = TaskStatus.FAILED
                    task.error = str(result or "")[:2000]
                    task.result = result
                else:
                    task.status = TaskStatus.COMPLETED
                    task.result = result
                self._active_count -= 1
                self._snapshot(task)

            append_task_event(
                task.task_id,
                task.status.value,
                str(result or task.error or task.status.value)[:1200],
                phase=task.status.value,
                metadata=task.metadata,
            )

            if task.on_complete:
                try:
                    callback_result = result if not task.cancel_flag.is_set() else "Task cancelled."
                    task.on_complete(task.task_id, callback_result)
                except Exception as e:
                    print(f"[TaskQueue] WARNING on_complete callback error: {e}")

            print(f"[TaskQueue] Finished: [{task.task_id}] {task.status.value}")
            log_event("task_queue", task.status.value, f"[{task.task_id}] {task.goal[:300]}")

        except Exception as e:
            with self._lock:
                task.status = TaskStatus.FAILED
                task.error  = str(e)
                self._active_count -= 1
                self._snapshot(task)
            append_task_event(
                task.task_id,
                "failed",
                str(e)[:1200],
                phase="failed",
                metadata=task.metadata,
            )
            print(f"[TaskQueue] Failed: [{task.task_id}] {e}")
            log_event("task_queue", "failed", f"[{task.task_id}] {task.goal[:300]} | {e}")
            if task.on_complete:
                try:
                    task.on_complete(task.task_id, f"Task failed: {e}")
                except Exception as callback_error:
                    print(f"[TaskQueue] WARNING on_complete callback error: {callback_error}")

        with self._condition:
            self._condition.notify()

_queue        = TaskQueue()
_queue_started = False
_queue_lock    = threading.Lock()


def get_queue() -> TaskQueue:
    global _queue_started
    with _queue_lock:
        if not _queue_started:
            _queue.start()
            _queue_started = True
    return _queue


def _looks_like_failed_result(result: Any) -> bool:
    text = str(result or "").strip().lower()
    if not text:
        return False
    return text.startswith(
        (
            "task failed",
            "task aborted",
            "i couldn't create a valid plan",
            "i could not create a valid plan",
            "task cancelled",
        )
    )
