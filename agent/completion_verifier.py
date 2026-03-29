# agent/completion_verifier.py
# AXIOM — Post-Execution Completion Verification
#
# Ensures tasks are actually completed rather than silently left half-done.
# Uses Gemini to assess whether the original goal was met, extract lessons,
# and suggest corrective actions when needed.

import re
import sys
from pathlib import Path
from dataclasses import dataclass, field

from core.secret_config import get_gemini_api_key
from memory.runtime_store import log_event, upsert_knowledge_item


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


@dataclass
class CompletionReport:
    """Result of verifying whether a goal was fully accomplished."""
    goal: str
    is_complete: bool
    confidence: float  # 0.0 to 1.0
    summary: str
    missing_items: list[str] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)
    corrective_steps: list[dict] = field(default_factory=list)


# Results that indicate nothing meaningful was done
_TRIVIAL_RESULTS = {
    "", "done.", "completed.", "command executed with no output.",
    "screen captured and analyzed.", "unknown action.",
}

# Patterns that suggest a tool failed silently
_SILENT_FAILURE_PATTERNS = (
    "could not",
    "couldn't",
    "unable to",
    "failed to",
    "error:",
    "timeout",
    "not found",
    "no results",
    "no data",
    "empty response",
    "none found",
)


def _get_api_key() -> str:
    return get_gemini_api_key()


def assess_result_quality(
    tool: str,
    result: str,
    goal_context: str = "",
) -> dict:
    """
    Assess whether a tool result actually accomplished something useful.
    Returns a dict with 'quality' (good/ambiguous/failed) and 'reason'.

    This replaces the naive `_looks_like_failed_result()` string-prefix check.
    """
    text = str(result or "").strip()
    lower = text.lower()

    if not text:
        return {"quality": "failed", "reason": "Empty result"}

    if lower in _TRIVIAL_RESULTS:
        return {"quality": "ambiguous", "reason": "Trivial result — may not indicate real completion"}

    # Check for silent failure patterns
    for pattern in _SILENT_FAILURE_PATTERNS:
        if lower.startswith(pattern) or (f" {pattern}" in lower and len(text) < 200):
            return {"quality": "failed", "reason": f"Result contains failure indicator: '{pattern}'"}

    # Check for explicit failure prefixes (original behavior)
    explicit_failure_starts = (
        "task failed",
        "task aborted",
        "i couldn't create a valid plan",
        "i could not create a valid plan",
        "task cancelled",
    )
    if lower.startswith(explicit_failure_starts):
        return {"quality": "failed", "reason": "Explicit failure message"}

    # Positive signals
    positive_signals = (
        "saved to:", "opened:", "file created:", "written to:",
        "playing youtube", "search results for:", "[deep search]",
        "[vane search]", "project directory:", "entry file:",
        "order placed!", "mt5 connected.",
    )
    if any(lower.startswith(sig) or sig in lower for sig in positive_signals):
        return {"quality": "good", "reason": "Contains positive completion signal"}

    # URLs and file paths are usually signs of real work
    if "http://" in text or "https://" in text or "C:\\" in text or "/home/" in text:
        return {"quality": "good", "reason": "Contains concrete artifact reference"}

    # If the result is substantial, it's probably meaningful
    if len(text) > 200:
        return {"quality": "good", "reason": "Substantial result content"}

    return {"quality": "ambiguous", "reason": "Could not confidently assess result quality"}


def verify_goal_completion(
    goal: str,
    completed_steps: list[dict],
    step_results: dict,
) -> CompletionReport:
    """
    Use Gemini to verify whether a goal was actually accomplished.
    Examines all step results against the original goal.
    """
    # Fast path: if all results look good, don't waste an API call
    all_good = True
    any_substance = False
    for step in completed_steps:
        step_num = step.get("step", "")
        result = str(step_results.get(step_num, "") or "").strip()
        assessment = assess_result_quality(step.get("tool", ""), result, goal)
        if assessment["quality"] == "failed":
            all_good = False
        if assessment["quality"] == "good":
            any_substance = True

    if all_good and any_substance:
        return CompletionReport(
            goal=goal,
            is_complete=True,
            confidence=0.85,
            summary="All steps completed with positive results.",
        )

    # Use Gemini for deeper verification
    try:
        from core import gemini_compat as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-3.1-flash-lite-preview")

        results_summary = []
        for step in completed_steps[:6]:
            step_num = step.get("step", "?")
            tool = step.get("tool", "unknown")
            desc = step.get("description", "")
            result = str(step_results.get(step_num, "") or "")[:500]
            results_summary.append(f"Step {step_num} [{tool}]: {desc}\nResult: {result}")

        prompt = f"""Assess whether this task was FULLY and CORRECTLY completed.

Original Goal: {goal}

Step Results:
{chr(10).join(results_summary)}

Respond in this EXACT format (no markdown, no extra text):
COMPLETE: yes/no
CONFIDENCE: 0.0-1.0
MISSING: comma-separated list of what's missing (or "none")
LESSON: one key takeaway from this execution (or "none")"""

        response = model.generate_content(prompt)
        text = response.text.strip()

        # Parse the response
        is_complete = "complete: yes" in text.lower()
        confidence = 0.5
        missing = []
        lessons = []

        for line in text.splitlines():
            line_lower = line.strip().lower()
            if line_lower.startswith("confidence:"):
                try:
                    confidence = float(re.search(r"[\d.]+", line).group())
                    confidence = min(1.0, max(0.0, confidence))
                except Exception:
                    pass
            elif line_lower.startswith("missing:"):
                raw = line.split(":", 1)[1].strip()
                if raw.lower() != "none":
                    missing = [item.strip() for item in raw.split(",") if item.strip()]
            elif line_lower.startswith("lesson:"):
                raw = line.split(":", 1)[1].strip()
                if raw.lower() != "none":
                    lessons = [raw]

        report = CompletionReport(
            goal=goal,
            is_complete=is_complete,
            confidence=confidence,
            summary=text[:500],
            missing_items=missing,
            lessons=lessons,
        )

        # Log the verification
        log_event(
            "verification",
            "goal_completion_check",
            f"{goal[:200]} → {'COMPLETE' if is_complete else 'INCOMPLETE'} ({confidence:.0%})",
            metadata={
                "is_complete": is_complete,
                "confidence": round(confidence, 2),
                "missing_count": len(missing),
            },
        )

        return report

    except Exception as e:
        print(f"[Verifier] ⚠️ Gemini verification failed: {e}")
        # Fall back to basic assessment
        return CompletionReport(
            goal=goal,
            is_complete=all_good,
            confidence=0.5,
            summary=f"Basic assessment (Gemini unavailable): {'likely complete' if all_good else 'may be incomplete'}",
        )


def extract_and_save_lessons(
    goal: str,
    report: CompletionReport,
    completed_steps: list[dict],
) -> None:
    """Save lessons learned from task execution to memory for future recall."""
    try:
        lessons = report.lessons
        if not lessons and not report.is_complete:
            lessons = [f"Task was incomplete. Missing: {', '.join(report.missing_items[:3])}"]

        if not lessons:
            return

        content_lines = [
            f"Goal: {goal}",
            f"Outcome: {'Success' if report.is_complete else 'Incomplete'}",
            f"Confidence: {report.confidence:.0%}",
        ]
        if report.missing_items:
            content_lines.append(f"Missing: {', '.join(report.missing_items[:5])}")
        content_lines.append(f"Lessons: {'; '.join(lessons)}")
        content_lines.append(f"Tools used: {', '.join(s.get('tool', '') for s in completed_steps[:6])}")

        upsert_knowledge_item(
            kind="task_lesson",
            title=f"Lesson: {goal[:80]}",
            content="\n".join(content_lines)[:6000],
            source="agent.completion_verifier",
            metadata={
                "is_complete": report.is_complete,
                "confidence": round(report.confidence, 2),
            },
        )

        log_event(
            "learning",
            "lesson_extracted",
            f"{goal[:200]}: {'; '.join(lessons)[:300]}",
            metadata={"is_complete": report.is_complete},
        )

    except Exception as e:
        print(f"[Verifier] ⚠️ Lesson save failed: {e}")
