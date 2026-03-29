# agent/self_monitor.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AXIOM Self-Monitor — Runtime health, resource tracking, anomaly detection
#
# Runs as a background daemon that tracks:
#   - System resources (CPU, RAM, disk)
#   - API call quota tracking
#   - Task execution duration monitoring
#   - Error rate tracking
#   - Health reporting
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import os
import sys
import time
import threading
import traceback
from pathlib import Path
from dataclasses import dataclass, field, asdict
from collections import deque
from typing import Optional

try:
    import psutil
    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class ResourceSnapshot:
    """Point-in-time resource usage."""
    timestamp: float = 0.0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    disk_free_gb: float = 0.0
    disk_percent_used: float = 0.0
    active_threads: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class APIQuota:
    """Track API call counts and rates."""
    total_calls: int = 0
    calls_last_minute: int = 0
    calls_last_hour: int = 0
    estimated_cost_usd: float = 0.0
    last_call_time: float = 0.0
    errors: int = 0
    _call_times: list = field(default_factory=list, repr=False)

    def record_call(self, is_error: bool = False):
        now = time.time()
        self.total_calls += 1
        self.last_call_time = now
        self._call_times.append(now)
        if is_error:
            self.errors += 1

        # Estimated cost: ~$0.0001 per flash-lite call, ~$0.001 per flash call
        self.estimated_cost_usd += 0.0005  # average

        # Clean old entries
        cutoff_minute = now - 60
        cutoff_hour = now - 3600
        self._call_times = [t for t in self._call_times if t > cutoff_hour]
        self.calls_last_minute = sum(1 for t in self._call_times if t > cutoff_minute)
        self.calls_last_hour = len(self._call_times)


@dataclass
class TaskMetrics:
    """Track task execution performance."""
    tasks_completed: int = 0
    tasks_failed: int = 0
    avg_duration_seconds: float = 0.0
    longest_task_seconds: float = 0.0
    longest_task_name: str = ""
    currently_running: str = ""
    current_start_time: float = 0.0
    _durations: list = field(default_factory=list, repr=False)

    def start_task(self, name: str):
        self.currently_running = name
        self.current_start_time = time.time()

    def end_task(self, success: bool = True):
        if self.current_start_time > 0:
            duration = time.time() - self.current_start_time
            self._durations.append(duration)
            # Keep last 50
            if len(self._durations) > 50:
                self._durations = self._durations[-50:]
            self.avg_duration_seconds = sum(self._durations) / len(self._durations)
            if duration > self.longest_task_seconds:
                self.longest_task_seconds = duration
                self.longest_task_name = self.currently_running
            if success:
                self.tasks_completed += 1
            else:
                self.tasks_failed += 1
        self.currently_running = ""
        self.current_start_time = 0.0

    @property
    def success_rate(self) -> float:
        total = self.tasks_completed + self.tasks_failed
        return self.tasks_completed / total if total > 0 else 1.0

    @property
    def current_duration(self) -> float:
        if self.current_start_time > 0:
            return time.time() - self.current_start_time
        return 0.0


@dataclass
class HealthReport:
    """Complete system health report."""
    status: str = "healthy"  # healthy, degraded, critical
    timestamp: float = 0.0
    resources: Optional[ResourceSnapshot] = None
    api_quota: Optional[APIQuota] = None
    task_metrics: Optional[TaskMetrics] = None
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "status": self.status,
            "timestamp": self.timestamp,
            "warnings": self.warnings,
            "errors": self.errors,
        }
        if self.resources:
            d["resources"] = self.resources.to_dict()
        if self.api_quota:
            d["api_quota"] = {
                "total_calls": self.api_quota.total_calls,
                "calls_last_minute": self.api_quota.calls_last_minute,
                "calls_last_hour": self.api_quota.calls_last_hour,
                "estimated_cost_usd": round(self.api_quota.estimated_cost_usd, 4),
                "errors": self.api_quota.errors,
            }
        if self.task_metrics:
            d["task_metrics"] = {
                "completed": self.task_metrics.tasks_completed,
                "failed": self.task_metrics.tasks_failed,
                "success_rate": round(self.task_metrics.success_rate, 2),
                "avg_duration_s": round(self.task_metrics.avg_duration_seconds, 1),
                "currently_running": self.task_metrics.currently_running,
                "current_duration_s": round(self.task_metrics.current_duration, 1),
            }
        return d


# ── Singleton Monitor ────────────────────────────────────────────────────────

class SelfMonitor:
    """Background self-monitoring daemon."""

    _instance: Optional["SelfMonitor"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.api_quota = APIQuota()
        self.task_metrics = TaskMetrics()
        self._resource_history: deque = deque(maxlen=60)  # last 60 snapshots
        self._warning_log: deque = deque(maxlen=100)
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started = False

    def start(self, interval: float = 30.0):
        """Start background monitoring."""
        if self._started:
            return
        self._started = True
        self._stop_event.clear()

        def _monitor_loop():
            while not self._stop_event.is_set():
                try:
                    snapshot = self._take_snapshot()
                    self._resource_history.append(snapshot)
                    self._check_thresholds(snapshot)
                except Exception as e:
                    print(f"[Monitor] WARNING snapshot error: {e}")
                self._stop_event.wait(interval)

        self._monitor_thread = threading.Thread(
            target=_monitor_loop, daemon=True, name="AxiomSelfMonitor"
        )
        self._monitor_thread.start()
        print("[Monitor] Self-monitor started")

    def stop(self):
        """Stop background monitoring."""
        self._stop_event.set()
        self._started = False

    def _take_snapshot(self) -> ResourceSnapshot:
        snap = ResourceSnapshot(timestamp=time.time())
        snap.active_threads = threading.active_count()

        if _PSUTIL_OK:
            try:
                proc = psutil.Process()
                snap.cpu_percent = proc.cpu_percent(interval=0.1)
                mem_info = proc.memory_info()
                snap.memory_mb = mem_info.rss / (1024 * 1024)
                snap.memory_percent = proc.memory_percent()

                disk = psutil.disk_usage(str(Path.home()))
                snap.disk_free_gb = disk.free / (1024 ** 3)
                snap.disk_percent_used = disk.percent
            except Exception:
                pass

        return snap

    def _check_thresholds(self, snap: ResourceSnapshot):
        """Check if any metrics are concerning."""
        now_str = time.strftime("%H:%M:%S")

        if snap.memory_percent > 80:
            w = f"[{now_str}] High memory: {snap.memory_mb:.0f}MB ({snap.memory_percent:.1f}%)"
            self._warning_log.append(w)
            if snap.memory_percent > 95:
                print(f"[Monitor] CRITICAL: {w}")

        if snap.disk_free_gb < 2.0:
            w = f"[{now_str}] Low disk: {snap.disk_free_gb:.1f}GB free"
            self._warning_log.append(w)

        if self.api_quota.calls_last_minute > 20:
            w = f"[{now_str}] High API rate: {self.api_quota.calls_last_minute} calls/min"
            self._warning_log.append(w)

        if self.task_metrics.current_duration > 300:  # 5 minutes
            w = f"[{now_str}] Long task: '{self.task_metrics.currently_running}' running {self.task_metrics.current_duration:.0f}s"
            self._warning_log.append(w)

    # ── Public API ───────────────────────────────────────────────────────

    def record_api_call(self, is_error: bool = False):
        """Record a Gemini API call."""
        self.api_quota.record_call(is_error)

    def start_task(self, name: str):
        """Mark a task as started."""
        self.task_metrics.start_task(name)

    def end_task(self, success: bool = True):
        """Mark current task as completed."""
        self.task_metrics.end_task(success)

    def get_health_report(self) -> HealthReport:
        """Generate a complete health report."""
        report = HealthReport(
            timestamp=time.time(),
            api_quota=self.api_quota,
            task_metrics=self.task_metrics,
        )

        # Latest resource snapshot
        if self._resource_history:
            report.resources = self._resource_history[-1]
        else:
            report.resources = self._take_snapshot()

        # Collect warnings
        report.warnings = list(self._warning_log)[-10:]  # last 10

        # Determine overall status
        if report.resources:
            if report.resources.memory_percent > 95:
                report.status = "critical"
                report.errors.append("Memory usage critical")
            elif report.resources.memory_percent > 80:
                report.status = "degraded"

        if self.task_metrics.success_rate < 0.5 and self.task_metrics.tasks_completed + self.task_metrics.tasks_failed > 3:
            report.status = "degraded"
            report.warnings.append(f"Low success rate: {self.task_metrics.success_rate:.0%}")

        if self.api_quota.errors > 10:
            report.status = "degraded"
            report.warnings.append(f"High API error count: {self.api_quota.errors}")

        return report

    def should_throttle(self) -> bool:
        """Check if we should slow down API calls."""
        return self.api_quota.calls_last_minute > 25

    def format_status(self) -> str:
        """Human-readable status string."""
        report = self.get_health_report()
        lines = [f"System Status: {report.status.upper()}"]

        if report.resources:
            r = report.resources
            lines.append(f"  Memory: {r.memory_mb:.0f}MB ({r.memory_percent:.1f}%)")
            lines.append(f"  Disk Free: {r.disk_free_gb:.1f}GB")
            lines.append(f"  Threads: {r.active_threads}")

        q = self.api_quota
        lines.append(f"  API Calls: {q.total_calls} total, {q.calls_last_minute}/min, {q.calls_last_hour}/hr")
        lines.append(f"  Est. Cost: ${q.estimated_cost_usd:.4f}")

        t = self.task_metrics
        lines.append(f"  Tasks: {t.tasks_completed} done, {t.tasks_failed} failed ({t.success_rate:.0%} success)")
        if t.currently_running:
            lines.append(f"  Running: '{t.currently_running}' ({t.current_duration:.0f}s)")

        if report.warnings:
            lines.append(f"  Warnings: {len(report.warnings)}")

        return "\n".join(lines)


# ── Module-level convenience functions ───────────────────────────────────────

_monitor = SelfMonitor()


def get_monitor() -> SelfMonitor:
    """Get the singleton monitor instance."""
    return _monitor


def get_health_report() -> HealthReport:
    """Get current health report."""
    return _monitor.get_health_report()


def record_api_call(is_error: bool = False):
    """Record an API call."""
    _monitor.record_api_call(is_error)


def start_task_tracking(name: str):
    """Start tracking a task."""
    _monitor.start_task(name)


def end_task_tracking(success: bool = True):
    """End tracking current task."""
    _monitor.end_task(success)


def format_status() -> str:
    """Get human-readable status."""
    return _monitor.format_status()


def start_monitoring(interval: float = 30.0):
    """Start the background monitor."""
    _monitor.start(interval)
