import os
import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from core.runtime_config import load_runtime_config
from memory.memory_manager import save_to_memory_archive
from memory.runtime_store import log_event


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
DEFAULT_PROJECTS_DIR = Path.home() / "Desktop" / "AXIOMProjects"
DEFAULT_MODEL = "gpt-5.4"


def _builder_config() -> dict:
    runtime = load_runtime_config()
    return runtime.get("builders", {}) or {}


def _codex_binary() -> str:
    cmd_shim = shutil.which("codex.cmd")
    if cmd_shim:
        return cmd_shim
    direct = shutil.which("codex")
    if direct:
        return direct
    npm_shim = Path.home() / "AppData" / "Roaming" / "npm" / "codex.cmd"
    if npm_shim.exists():
        return str(npm_shim)
    npm_ps1 = Path.home() / "AppData" / "Roaming" / "npm" / "codex.ps1"
    if npm_ps1.exists():
        return str(npm_ps1)
    return ""


def _projects_dir() -> Path:
    configured = str(_builder_config().get("projects_dir", "") or "").strip()
    root = Path(configured) if configured else DEFAULT_PROJECTS_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return slug[:48] or "axiom-project"


def _derive_project_name(description: str, explicit_name: str = "") -> str:
    if explicit_name:
        return _slugify(explicit_name)
    text = str(description or "").strip()
    for marker in (" called ", " named ", " project ", " app ", " game ", " website "):
        if marker in f" {text.lower()} ":
            tail = text.lower().split(marker, 1)[1].strip()
            candidate = _slugify(" ".join(tail.split()[:4]))
            if candidate:
                return candidate
    return _slugify(" ".join(text.split()[:6]))


def _resolve_project_dir(description: str, project_name: str = "", project_path: str = "") -> Path:
    if project_path:
        path = Path(project_path)
        return path if path.is_absolute() else _projects_dir() / path

    root = _projects_dir()
    base = root / _derive_project_name(description, explicit_name=project_name)
    if not base.exists():
        return base
    for index in range(2, 100):
        candidate = root / f"{base.name}-{index}"
        if not candidate.exists():
            return candidate
    return root / f"{base.name}-{os.getpid()}"


def _default_model() -> str:
    configured = str(_builder_config().get("codex_model", "") or "").strip()
    return configured or DEFAULT_MODEL


def _wants_static_build(description: str) -> bool:
    normalized = str(description or "").lower()
    light_words = (
        "website",
        "landing page",
        "portfolio",
        "dashboard",
        "browser",
        "html",
        "game",
        "playable",
        "snake",
        "arcade",
        "demo",
    )
    return any(word in normalized for word in light_words)


def _compose_prompt(description: str, project_dir: Path) -> str:
    static_bias = ""
    if _wants_static_build(description):
        static_bias = (
            "If the request can be satisfied with a local static build, prefer HTML/CSS/JS with no "
            "extra install step so AXIOM can open it immediately.\n"
        )

    return (
        "You are Codex operating as AXIOM's strongest build path.\n"
        "Create or update files directly in the current workspace.\n"
        "Deliver a real runnable artifact, not pseudo-code or placeholders.\n"
        f"Workspace: {project_dir}\n\n"
        "Quality rules:\n"
        "- Do not produce generic AI-slop UI.\n"
        "- Use an intentional visual direction, strong typography, and clear structure.\n"
        "- If the project is a website, app, or game, make it immediately usable.\n"
        "- Run the minimum verification needed and fix obvious issues before finishing.\n"
        "- Never claim a URL, file, or playable artifact exists unless you created it.\n"
        f"{static_bias}\n"
        "When done, print exactly this block:\n"
        "AXIOM_RESULT\n"
        f"project_dir: {project_dir}\n"
        "entry_path: <main entry file or primary artifact>\n"
        "open_target: <local file path or URL to open first>\n"
        "run_command: <command to run or open, or none>\n"
        "summary: <one-line summary>\n"
        "END_AXIOM_RESULT\n\n"
        f"User request:\n{description.strip()}\n"
    )


def _parse_result_block(text: str) -> dict:
    block_match = re.search(
        r"AXIOM_RESULT\s*(.*?)\s*END_AXIOM_RESULT",
        str(text or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not block_match:
        return {}

    result = {}
    for raw_line in block_match.group(1).splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip().lower()] = value.strip()
    return result


def _infer_entry_path(project_dir: Path) -> str:
    preferred = (
        project_dir / "index.html",
        project_dir / "app.html",
        project_dir / "main.py",
        project_dir / "package.json",
        project_dir / "README.md",
    )
    for candidate in preferred:
        if candidate.exists():
            return str(candidate)

    for pattern in ("*.html", "*.py", "*.js", "*.ts"):
        matches = sorted(project_dir.rglob(pattern))
        if matches:
            return str(matches[0])
    return ""


def _infer_open_target(project_dir: Path, parsed: dict) -> str:
    explicit = str(parsed.get("open_target", "") or "").strip()
    if explicit and explicit.lower() != "none":
        return explicit

    entry_path = str(parsed.get("entry_path", "") or "").strip()
    if entry_path and entry_path.lower() != "none":
        return entry_path

    return _infer_entry_path(project_dir)


def _open_target(target: str) -> str:
    target = str(target or "").strip()
    if not target or target.lower() == "none":
        return ""
    try:
        if target.startswith(("http://", "https://", "file:///")):
            webbrowser.open(target)
            return f"Opened: {target}"

        path = Path(target)
        if path.exists():
            if os.name == "nt":
                os.startfile(str(path))
            else:
                webbrowser.open(path.resolve().as_uri())
            return f"Opened: {path}"
    except Exception as exc:
        return f"Open failed: {exc}"
    return ""


def codex_builder(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "build") or "build").strip().lower()
    codex_bin = _codex_binary()
    model = str(params.get("model", "") or "").strip() or _default_model()

    if action == "status":
        return (
            "Codex builder status\n"
            f"Codex binary: {codex_bin or 'missing'}\n"
            f"Default model: {model}\n"
            f"Projects dir: {_projects_dir()}"
        )

    if action != "build":
        return "Unknown action. Use build or status."

    if not codex_bin:
        return "Codex CLI is not installed on this machine."

    description = str(params.get("description", "") or "").strip()
    if not description:
        return "Codex builder needs a project description."

    timeout = int(params.get("timeout", 900) or 900)
    open_when_done = bool(params.get("open_when_done", False))
    project_dir = _resolve_project_dir(
        description=description,
        project_name=str(params.get("project_name", "") or "").strip(),
        project_path=str(params.get("project_path", "") or "").strip(),
    )
    project_dir.mkdir(parents=True, exist_ok=True)

    prompt = _compose_prompt(description, project_dir)
    command = [
        codex_bin,
        "exec",
        "-C",
        str(project_dir),
        "--full-auto",
        "--skip-git-repo-check",
        "--ephemeral",
        "-m",
        model,
        "-",
    ]

    if player:
        player.write_log(f"[Codex] Building in {project_dir}")

    log_event(
        "codex_builder",
        "build_started",
        description[:300],
        metadata={"project_dir": str(project_dir), "model": model},
    )

    try:
        completed = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(timeout, 60),
            cwd=str(project_dir),
        )
    except subprocess.TimeoutExpired:
        return f"Task failed. Codex build timed out after {timeout}s in {project_dir}"
    except Exception as exc:
        return f"Task failed. Codex build could not start: {exc}"

    output = "\n".join(
        part.strip() for part in (completed.stdout or "", completed.stderr or "") if part.strip()
    ).strip()
    log_path = project_dir / ".axiom_codex_last_run.txt"
    try:
        log_path.write_text(output, encoding="utf-8")
    except Exception:
        pass

    parsed = _parse_result_block(output)
    entry_path = str(parsed.get("entry_path", "") or "").strip()
    if not entry_path or entry_path.lower() == "none":
        entry_path = _infer_entry_path(project_dir)

    open_target = _infer_open_target(project_dir, parsed)
    run_command = str(parsed.get("run_command", "") or "").strip()
    summary = str(parsed.get("summary", "") or "").strip()

    if completed.returncode != 0:
        error_excerpt = output[-600:] if output else "No CLI output was captured."
        log_event(
            "codex_builder",
            "build_failed",
            error_excerpt[:500],
            metadata={"project_dir": str(project_dir), "returncode": completed.returncode},
        )
        return (
            "Task failed. Codex builder exited with an error.\n"
            f"Project directory: {project_dir}\n"
            f"Run log: {log_path}\n"
            f"Output: {error_excerpt}"
        )

    open_result = _open_target(open_target) if open_when_done else ""
    lines = [
        f"Project directory: {project_dir}",
        f"Entry file: {entry_path or 'not identified'}",
        f"Open target: {open_target or 'not identified'}",
        f"Run command: {run_command or 'none'}",
    ]
    if summary:
        lines.append(f"Summary: {summary}")
    if open_result:
        lines.append(open_result)
    lines.append(f"Run log: {log_path}")

    result_text = "\n".join(lines)
    log_event(
        "codex_builder",
        "build_finished",
        result_text[:500],
        metadata={"project_dir": str(project_dir), "entry_path": entry_path, "open_target": open_target},
    )
    try:
        save_to_memory_archive(
            f"Codex Build {project_dir.name}",
            result_text,
            kind="build",
            source="codex_builder",
            metadata={"project_dir": str(project_dir)},
        )
    except Exception:
        pass

    if speak:
        speak(f"Codex build complete. Primary artifact is at {open_target or entry_path or project_dir}.")

    return result_text
