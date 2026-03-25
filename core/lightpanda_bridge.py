import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

from core.runtime_config import load_runtime_config, update_runtime_config


DEFAULT_LIGHTPANDA_ENDPOINT = "http://127.0.0.1:9222"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def configure_lightpanda(updates: dict) -> dict:
    return update_runtime_config({"browser": updates or {}})


def _browser_config() -> dict:
    return load_runtime_config().get("browser", {}) or {}


def _path_or_none(value: str | Path | None) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _candidate_repo_paths() -> list[Path]:
    cfg = _browser_config()
    return [
        path
        for path in [
            _path_or_none(cfg.get("lightpanda_repo_path", "")),
            Path.home() / "Axiom_research" / "external" / "lightpanda-browser",
        ]
        if path is not None
    ]


def resolve_lightpanda_repo_path() -> Path | None:
    for candidate in _candidate_repo_paths():
        try:
            if candidate.exists() and (candidate / "README.md").exists() and (candidate / "build.zig").exists():
                return candidate
        except Exception:
            continue
    return None


def _bridge_logs_dir(name: str) -> Path:
    candidates = [
        BASE_DIR / ".axiom_logs" / "integrations" / name,
        Path.home() / ".axiom_logs" / "integrations" / name,
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue
    raise PermissionError("AXIOM could not create an integration log directory.")


def _windows_creationflags() -> list[int]:
    if os.name != "nt":
        return [0]
    create_new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    detached = getattr(subprocess, "DETACHED_PROCESS", 0)
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    flags = [
        create_new_group | detached | no_window | breakaway,
        create_new_group | detached | no_window,
        create_new_group | no_window,
        0,
    ]
    return list(dict.fromkeys(flags))


def lightpanda_endpoint() -> str:
    cfg = _browser_config()
    endpoint = str(cfg.get("lightpanda_endpoint", "") or DEFAULT_LIGHTPANDA_ENDPOINT).strip()
    return endpoint or DEFAULT_LIGHTPANDA_ENDPOINT


def _http_json(url: str, timeout: float = 2.5) -> tuple[dict | None, str]:
    try:
        with urlrequest.urlopen(url, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        if not raw.strip():
            return {}, ""
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}, ""
    except urlerror.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except urlerror.URLError as exc:
        return None, str(exc.reason or exc)
    except Exception as exc:
        return None, str(exc)


def _endpoint_http_base(endpoint: str) -> str:
    value = str(endpoint or "").strip().rstrip("/")
    if value.startswith("ws://"):
        return "http://" + value[5:]
    if value.startswith("wss://"):
        return "https://" + value[6:]
    return value


def _endpoint_host_port(endpoint: str) -> tuple[str, int]:
    parsed = urlparse(_endpoint_http_base(endpoint))
    host = parsed.hostname or "127.0.0.1"
    if parsed.port:
        return host, parsed.port
    if parsed.scheme == "https":
        return host, 443
    return host, 80


def _read_text(path: Path, limit: int = 900) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit].strip()
    except Exception:
        return ""


def lightpanda_version_info() -> dict:
    endpoint = lightpanda_endpoint()
    base = _endpoint_http_base(endpoint)
    payload, error_text = _http_json(f"{base}/json/version")
    if isinstance(payload, dict):
        return {
            "reachable": True,
            "endpoint": endpoint,
            "http_base": base,
            "payload": payload,
            "error": "",
        }
    return {
        "reachable": False,
        "endpoint": endpoint,
        "http_base": base,
        "payload": {},
        "error": error_text,
    }


def resolve_lightpanda_ws_endpoint() -> str:
    endpoint = lightpanda_endpoint()
    if endpoint.startswith(("ws://", "wss://")):
        return endpoint
    info = lightpanda_version_info()
    payload = info.get("payload", {}) or {}
    ws_endpoint = str(payload.get("webSocketDebuggerUrl", "") or "").strip()
    if ws_endpoint:
        ws_endpoint = ws_endpoint.replace("ws://0.0.0.0:", "ws://127.0.0.1:")
        ws_endpoint = ws_endpoint.replace("wss://0.0.0.0:", "wss://127.0.0.1:")
        return ws_endpoint
    if endpoint.startswith("http://"):
        return "ws://" + endpoint[7:].rstrip("/")
    if endpoint.startswith("https://"):
        return "wss://" + endpoint[8:].rstrip("/")
    return endpoint


def _find_lightpanda_binary(repo_path: Path | None) -> str:
    candidates: list[Path] = []
    if repo_path is not None:
        candidates.extend(
            [
                repo_path / "zig-out" / "bin" / "lightpanda.exe",
                repo_path / "zig-out" / "bin" / "lightpanda",
                repo_path / "lightpanda.exe",
                repo_path / "lightpanda",
            ]
        )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def _command_version(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=4,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return ""
    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return ""
    return output.splitlines()[0][:180]


def _command_text(command: list[str], timeout: int = 6) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return ""
    return (result.stdout or result.stderr or "").strip()


def _resolve_wsl_command() -> str:
    direct = shutil.which("wsl")
    if direct:
        return direct
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidate = system_root / "System32" / "wsl.exe"
    if candidate.exists():
        return str(candidate)
    return ""


def _find_wsl_lightpanda_binary() -> str:
    configured_path = str(_browser_config().get("lightpanda_wsl_binary_path", "") or "").strip()
    if configured_path and "/" in configured_path and "lightpanda" in configured_path:
        return configured_path

    wsl_command = _resolve_wsl_command()
    if not wsl_command:
        return ""
    output = _command_text(
        [
            wsl_command,
            "bash",
            "-lc",
            "command -v lightpanda || { test -x ~/.local/bin/lightpanda && printf '%s\\n' ~/.local/bin/lightpanda; }",
        ],
        timeout=8,
    )
    if not output:
        return ""
    first_line = output.replace("\x00", "").splitlines()[0].strip()
    if "lightpanda" not in first_line or "/" not in first_line:
        return ""
    return first_line


def collect_lightpanda_status() -> dict:
    repo = resolve_lightpanda_repo_path()
    info = lightpanda_version_info()
    payload = info.get("payload", {}) or {}
    browser_cfg = _browser_config()
    binary_path = _find_lightpanda_binary(repo)
    wsl_binary_path = _find_wsl_lightpanda_binary()
    return {
        "repo_path": str(repo) if repo else "",
        "binary_path": binary_path,
        "wsl_binary_path": wsl_binary_path,
        "backend": str(browser_cfg.get("backend", "playwright") or "playwright"),
        "auto_connect": bool(browser_cfg.get("lightpanda_auto_connect", False)),
        "auto_start": bool(browser_cfg.get("lightpanda_auto_start", False)),
        "endpoint": lightpanda_endpoint(),
        "ws_endpoint": resolve_lightpanda_ws_endpoint(),
        "reachable": bool(info.get("reachable")),
        "error": str(info.get("error", "") or "").strip(),
        "browser_name": str(payload.get("Browser", "") or "").strip(),
        "protocol_version": str(payload.get("Protocol-Version", "") or "").strip(),
        "user_agent": str(payload.get("User-Agent", "") or "").strip(),
        "docker_available": bool(shutil.which("docker")),
        "zig_available": bool(shutil.which("zig")),
        "cargo_available": bool(shutil.which("cargo")),
        "wsl_available": bool(_resolve_wsl_command()),
        "repo_version_hint": _command_version([binary_path, "--version"]) if binary_path else "",
    }


def format_lightpanda_status() -> str:
    status = collect_lightpanda_status()
    lines = [
        "Lightpanda integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"Browser backend setting: {status['backend']}",
        f"Auto-connect: {'yes' if status['auto_connect'] else 'no'}",
        f"Auto-start: {'yes' if status['auto_start'] else 'no'}",
        f"Endpoint: {status['endpoint']}",
        f"Resolved WS endpoint: {status['ws_endpoint']}",
        f"Endpoint reachable: {'yes' if status['reachable'] else 'no'}",
        f"Bundled/built binary: {status['binary_path'] or 'not found'}",
        f"WSL binary: {status['wsl_binary_path'] or 'not found'}",
        f"Docker available: {'yes' if status['docker_available'] else 'no'}",
        f"Zig available: {'yes' if status['zig_available'] else 'no'}",
        f"Cargo available: {'yes' if status['cargo_available'] else 'no'}",
        f"WSL available: {'yes' if status['wsl_available'] else 'no'}",
    ]
    if status["browser_name"]:
        lines.append(f"Reported browser: {status['browser_name']}")
    if status["protocol_version"]:
        lines.append(f"Protocol version: {status['protocol_version']}")
    if status["user_agent"]:
        lines.append(f"User agent: {status['user_agent']}")
    if status["repo_version_hint"]:
        lines.append(f"Binary version hint: {status['repo_version_hint']}")
    if status["error"]:
        lines.append(f"Endpoint error: {status['error']}")
    return "\n".join(lines)


def lightpanda_launch_instructions() -> str:
    status = collect_lightpanda_status()
    if status["binary_path"]:
        return (
            "Lightpanda can be launched directly with:\n"
            f"'{status['binary_path']}' serve --host 127.0.0.1 --port 9222\n\n"
            f"Then point Axiom at {status['endpoint']} and set browser.backend='lightpanda'."
        )

    if status["wsl_binary_path"]:
        return (
            "Lightpanda can be launched from WSL with:\n"
            f"wsl bash -lc \"LIGHTPANDA_DISABLE_TELEMETRY=true nohup {status['wsl_binary_path']} "
            "serve --host 0.0.0.0 --port 9222 >/tmp/axiom-lightpanda.log 2>&1 &\"\n\n"
            f"Then point Axiom at {status['endpoint']} and set browser.backend='lightpanda'."
        )

    if status["docker_available"]:
        return (
            "Lightpanda can be launched through Docker with:\n"
            "docker run -d --name lightpanda -p 9222:9222 lightpanda/browser:nightly\n\n"
            f"Then point Axiom at {status['endpoint']} and set browser.backend='lightpanda'."
        )

    if status["wsl_available"]:
        return (
            "This machine does not have a Lightpanda binary yet. The upstream project documents "
            "Windows usage through WSL2. Install Lightpanda inside WSL, expose port 9222, then set:\n"
            f"browser.lightpanda_endpoint = '{status['endpoint']}'"
        )

    return (
        "Lightpanda is cloned but not provisioned on this machine. Either build it with Zig/Rust, "
        "or run the official Docker image, then set browser.backend to 'lightpanda'."
    )


def start_lightpanda_backend(timeout: float = 12.0) -> dict:
    status = collect_lightpanda_status()
    if status["reachable"]:
        return {
            "started": True,
            "already_running": True,
            "endpoint": status["endpoint"],
            "ws_endpoint": status["ws_endpoint"],
            "message": "Lightpanda endpoint is already reachable.",
        }

    host, port = _endpoint_host_port(status["endpoint"])
    repo_path = Path(status["repo_path"]) if status["repo_path"] else None
    binary_path = str(status["binary_path"] or "").strip()

    if binary_path:
        log_path = _bridge_logs_dir("lightpanda") / "backend.log"
        try:
            log_handle = open(log_path, "a", encoding="utf-8")
        except Exception as exc:
            return {
                "started": False,
                "endpoint": status["endpoint"],
                "log_path": str(log_path),
                "message": f"AXIOM could not open the Lightpanda bridge log: {exc}",
            }

        process = None
        last_error = None
        command = [binary_path, "serve", "--host", host, "--port", str(port)]
        try:
            for creationflags in _windows_creationflags():
                try:
                    process = subprocess.Popen(
                        command,
                        cwd=str(repo_path or Path(binary_path).parent),
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        creationflags=creationflags,
                    )
                    break
                except Exception as exc:
                    last_error = exc
        finally:
            try:
                log_handle.close()
            except Exception:
                pass

        if process is None:
            return {"started": False, "message": f"Failed to launch Lightpanda: {last_error}"}

        deadline = time.time() + max(float(timeout or 0), 1.0)
        while time.time() < deadline:
            current = collect_lightpanda_status()
            if current["reachable"]:
                return {
                    "started": True,
                    "pid": process.pid,
                    "endpoint": current["endpoint"],
                    "ws_endpoint": current["ws_endpoint"],
                    "log_path": str(log_path),
                    "message": "Lightpanda launched successfully.",
                }
            if process.poll() is not None:
                break
            time.sleep(0.5)

        return {
            "started": False,
            "pid": process.pid,
            "endpoint": status["endpoint"],
            "log_path": str(log_path),
            "message": "Lightpanda launch was attempted but the endpoint never became reachable.",
            "log_excerpt": _read_text(log_path, limit=900),
        }

    if status["docker_available"]:
        command = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            "axiom-lightpanda",
            "-p",
            f"{port}:9222",
            "lightpanda/browser:nightly",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(int(timeout), 15),
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:
            return {"started": False, "message": f"Failed to run Docker for Lightpanda: {exc}"}

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            return {
                "started": False,
                "endpoint": status["endpoint"],
                "message": f"Docker launch failed: {detail[:260] or 'unknown error'}",
            }

        deadline = time.time() + max(float(timeout or 0), 1.0)
        while time.time() < deadline:
            current = collect_lightpanda_status()
            if current["reachable"]:
                return {
                    "started": True,
                    "endpoint": current["endpoint"],
                    "ws_endpoint": current["ws_endpoint"],
                    "message": "Lightpanda Docker container launched successfully.",
                }
            time.sleep(0.5)

        return {
            "started": False,
            "endpoint": status["endpoint"],
            "message": "Lightpanda Docker launch was attempted but the endpoint never became reachable.",
        }

    if status["wsl_binary_path"]:
        wsl_command = _resolve_wsl_command()
        if not wsl_command:
            return {
                "started": False,
                "endpoint": status["endpoint"],
                "message": "Lightpanda WSL launch is configured, but wsl.exe is not currently available.",
            }
        wsl_log_path = "/tmp/axiom-lightpanda.log"
        script = (
            "export LIGHTPANDA_DISABLE_TELEMETRY=true; "
            f"nohup {status['wsl_binary_path']} serve --host 0.0.0.0 --port {port} "
            f">{wsl_log_path} 2>&1 < /dev/null & echo $!"
        )
        pid_text = _command_text([wsl_command, "bash", "-lc", script], timeout=10)
        deadline = time.time() + max(float(timeout or 0), 1.0)
        while time.time() < deadline:
            current = collect_lightpanda_status()
            if current["reachable"]:
                return {
                    "started": True,
                    "pid": pid_text.splitlines()[-1].strip() if pid_text else "",
                    "endpoint": current["endpoint"],
                    "ws_endpoint": current["ws_endpoint"],
                    "log_path": wsl_log_path,
                    "message": "Lightpanda launched successfully inside WSL.",
                }
            time.sleep(0.5)
        return {
            "started": False,
            "endpoint": status["endpoint"],
            "log_path": wsl_log_path,
            "message": "Lightpanda WSL launch was attempted but the endpoint never became reachable.",
            "log_excerpt": _command_text([wsl_command, "bash", "-lc", f"tail -n 30 {wsl_log_path}"], timeout=8)[:900],
        }

    return {
        "started": False,
        "endpoint": status["endpoint"],
        "message": "Lightpanda cannot be started yet because no local binary or Docker runtime is available.",
    }
