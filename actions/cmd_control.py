import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from memory.runtime_store import log_event

try:
    import pyautogui

    pyautogui.PAUSE = 0.05
    _PYAUTOGUI = True
except Exception:
    _PYAUTOGUI = False

try:
    import pyperclip

    _PYPERCLIP = True
except Exception:
    _PYPERCLIP = False


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)["gemini_api_key"]


def _get_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _default_shell() -> str:
    return "powershell" if _get_platform() == "windows" else "bash"


def _normalize_shell(shell: str, command: str = "") -> str:
    normalized = str(shell or "").strip().lower()
    command_text = str(command or "").strip().lower()

    if not normalized:
        if command_text.startswith(("powershell ", "pwsh ")):
            return "powershell"
        if command_text.startswith("cmd /c"):
            return "cmd"
        return _default_shell()

    aliases = {
        "ps": "powershell",
        "powershell.exe": "powershell",
        "pwsh": "pwsh",
        "pwsh.exe": "pwsh",
        "command prompt": "cmd",
        "terminal": _default_shell(),
        "shell": _default_shell(),
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"powershell", "pwsh", "cmd", "bash"}:
        return _default_shell()
    if normalized == "pwsh" and not shutil.which("pwsh"):
        return "powershell"
    return normalized


def _shortcut_dir(name: str) -> Path | None:
    key = str(name or "").strip().lower()
    mapping = {
        "home": Path.home(),
        "desktop": Path.home() / "Desktop",
        "downloads": Path.home() / "Downloads",
        "documents": Path.home() / "Documents",
        "repo": BASE_DIR,
        "workspace": BASE_DIR,
    }
    return mapping.get(key)


def _resolve_workdir(cwd: str = "", task: str = "", command: str = "") -> Path:
    raw = str(cwd or "").strip()
    if raw:
        shortcut = _shortcut_dir(raw)
        candidate = shortcut or Path(raw)
        return candidate if candidate.is_absolute() else (BASE_DIR / candidate)

    hint_blob = f"{task}\n{command}".lower()
    if any(token in hint_blob for token in ("repo", "workspace", "project", "codex", "vs code", "vscode", "codebase")):
        return BASE_DIR
    return Path.home()


WIN_COMMAND_MAP = [
    (["disk space", "disk usage", "storage", "free space", "c drive space"], "wmic logicaldisk get caption,freespace,size /format:list"),
    (["running processes", "list processes", "show processes", "active processes", "tasklist"], "tasklist /fo table"),
    (["ip address", "my ip", "network info", "ipconfig"], "ipconfig /all"),
    (["ping", "internet connection", "connected to internet"], "ping -n 4 google.com"),
    (["open ports", "listening ports", "netstat"], "netstat -an | findstr LISTENING"),
    (["wifi networks", "available wifi", "wireless networks"], "netsh wlan show networks"),
    (["system info", "computer info", "hardware info", "pc info", "specs"], "systeminfo"),
    (["cpu usage", "processor usage"], "wmic cpu get loadpercentage"),
    (["memory usage", "ram usage"], "wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /Value"),
    (["windows version", "os version"], "ver"),
    (["installed programs", "installed software", "installed apps"], "wmic product get name,version /format:table"),
    (["battery", "battery level", "power status"], "(Get-WmiObject -Class Win32_Battery).EstimatedChargeRemaining"),
    (["current time", "what time", "system time"], "Get-Date -Format T"),
    (["current date", "what date", "system date"], "Get-Date -Format d"),
]


def _find_hardcoded(task: str) -> tuple[str, str | None]:
    task_lower = str(task or "").lower()
    if not task_lower:
        return "", None

    if "notepad" in task_lower or any(ext in task_lower for ext in [".txt", ".log", ".md", ".csv"]):
        file_match = re.search(r'[\"\']?([\S]+\.(?:txt|log|md|csv|json|xml))[\"\']?', task, re.IGNORECASE)
        if file_match:
            filename = file_match.group(1)
            desktop = Path.home() / "Desktop"
            filepath = Path(filename) if Path(filename).is_absolute() else desktop / filename
            return f'notepad "{filepath}"', "cmd"
        if "notepad" in task_lower:
            return "notepad", "cmd"

    pip_match = re.search(r"install\s+([\w\-\.]+)", task_lower)
    if pip_match:
        package = pip_match.group(1)
        return f"{sys.executable} -m pip install {package}", "cmd"

    if "codex status" in task_lower or ("codex" in task_lower and "status" in task_lower):
        return "codex --help", "powershell"
    if "code ." in task_lower or ("open" in task_lower and "vs code" in task_lower):
        return "code .", "cmd"

    for keywords, command in WIN_COMMAND_MAP:
        if any(kw in task_lower for kw in keywords):
            shell = "powershell" if "Get-" in command or "WmiObject" in command else "cmd"
            return command, shell

    return "", None


BLOCKED_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\brmdir\s+/s\b",
    r"\bdel\s+/[fqs]",
    r"\bremove-item\b.+\b-force\b",
    r"(^|[;&|])\s*format(?:\.com|\.exe)?\s+[A-Za-z]:",
    r"\bcmd(?:\.exe)?\s+/c\s+format(?:\.com|\.exe)?\s+[A-Za-z]:",
    r"\bdiskpart\b",
    r"\bfdisk\b",
    r"\breg\s+(delete|add)\b",
    r"\bbcdedit\b",
    r"\bset-executionpolicy\b",
    r"\bshutdown\b",
    r"\brestart-computer\b",
    r"\bstop-computer\b",
    r"\bstop-process\b",
    r"\bkill\s+-9\b",
    r"\btaskkill\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+checkout\s+--\b",
    r"\bgit\s+clean\s+-fd",
    r"\beval\b",
    r"\b__import__\b",
]
_BLOCKED_RE = re.compile("|".join(BLOCKED_PATTERNS), re.IGNORECASE)


def _is_safe(command: str) -> tuple[bool, str]:
    match = _BLOCKED_RE.search(str(command or ""))
    if match:
        return False, f"Blocked pattern: '{match.group()}'"
    return True, "OK"


def _ask_gemini(task: str, shell: str) -> str:
    try:
        import google.generativeai as genai

        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash-lite")

        shell_name = {
            "powershell": "Windows PowerShell",
            "pwsh": "PowerShell",
            "cmd": "Windows CMD",
            "bash": "Bash",
        }.get(shell, shell)
        wrapper_rule = {
            "powershell": "Return only the inner PowerShell command. Do not prefix it with powershell -Command.",
            "pwsh": "Return only the inner PowerShell command. Do not prefix it with pwsh -Command.",
            "cmd": "Return only the CMD command. Do not prefix it with cmd /c.",
            "bash": "Return only the Bash command. Do not prefix it with bash -lc.",
        }.get(shell, "")

        prompt = (
            f"Convert this request to a single {shell_name} command.\n"
            "Output ONLY the command. No explanation, no markdown, no backticks.\n"
            "If unsafe or impossible, output exactly: UNSAFE\n"
            f"{wrapper_rule}\n\n"
            f"Request: {task}\n\nCommand:"
        )
        response = model.generate_content(prompt)
        command = response.text.strip().strip("`").strip()
        if command.startswith("```"):
            lines = command.splitlines()
            command = "\n".join(lines[1:-1]).strip()
        return command
    except Exception as error:
        return f"ERROR: {error}"


def _strip_shell_wrapper(command: str, shell: str) -> str:
    text = str(command or "").strip()
    if not text:
        return text
    if shell in {"powershell", "pwsh"}:
        text = re.sub(r"^(powershell|pwsh)(?:\.exe)?\s+-NoProfile\s+-Command\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^(powershell|pwsh)(?:\.exe)?\s+", "", text, flags=re.IGNORECASE)
    elif shell == "cmd":
        text = re.sub(r"^cmd(?:\.exe)?\s+/c\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^cmd(?:\.exe)?\s+", "", text, flags=re.IGNORECASE)
    elif shell == "bash":
        text = re.sub(r"^bash\s+-lc\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^bash\s+", "", text, flags=re.IGNORECASE)
    return text.strip().strip('"')


def _ps_quote(text: str) -> str:
    return "'" + str(text or "").replace("'", "''") + "'"


def _compose_command(command: str, shell: str, cwd: Path | None) -> str:
    inner = _strip_shell_wrapper(command, shell)
    if not cwd:
        return inner
    if shell in {"powershell", "pwsh"}:
        return f"Set-Location -LiteralPath {_ps_quote(str(cwd))}; {inner}"
    if shell == "cmd":
        return f'cd /d "{cwd}" && {inner}'
    return f"cd {_ps_quote(str(cwd))} && {inner}"


def _run_silent(command: str, timeout: int = 20, shell: str = "", cwd: Path | None = None) -> str:
    try:
        platform_name = _get_platform()
        chosen_shell = _normalize_shell(shell, command)
        final_command = _compose_command(command, chosen_shell, cwd)

        if platform_name == "windows":
            if chosen_shell in {"powershell", "pwsh"}:
                binary = "pwsh" if chosen_shell == "pwsh" and shutil.which("pwsh") else "powershell"
                result = subprocess.run(
                    [binary, "-NoProfile", "-Command", final_command],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    cwd=str(cwd or Path.home()),
                )
            elif chosen_shell == "cmd":
                result = subprocess.run(
                    ["cmd", "/c", final_command],
                    capture_output=True,
                    text=True,
                    encoding="cp1252",
                    errors="replace",
                    timeout=timeout,
                    cwd=str(cwd or Path.home()),
                )
            else:
                result = subprocess.run(
                    ["bash", "-lc", final_command],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    cwd=str(cwd or Path.home()),
                )
        else:
            binary = "/bin/zsh" if platform_name == "macos" else "/bin/bash"
            result = subprocess.run(
                final_command,
                shell=True,
                executable=binary,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                cwd=str(cwd or Path.home()),
            )

        output = result.stdout.strip()
        error = result.stderr.strip()
        if output:
            return output[:4000]
        if error:
            return f"[stderr]: {error[:1200]}"
        return "Command executed with no output."
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s."
    except Exception as error:
        return f"Execution error: {error}"


def _activate_window(title_fragment: str) -> None:
    if _get_platform() != "windows":
        return
    script = (
        "$wshell = New-Object -ComObject WScript.Shell; "
        f"$null = $wshell.AppActivate({_ps_quote(title_fragment)});"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=4,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        pass


def _paste_or_type(text: str) -> None:
    if _PYPERCLIP:
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        return
    pyautogui.write(text, interval=0.01)


def _code_binary() -> str:
    direct = shutil.which("code.cmd") or shutil.which("code")
    if direct:
        return direct
    local = Path.home() / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "Code.exe"
    return str(local) if local.exists() else ""


def _open_vscode_workspace(cwd: Path) -> bool:
    code_bin = _code_binary()
    if not code_bin:
        return False
    try:
        subprocess.Popen(
            [code_bin, "-r", str(cwd)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(cwd),
        )
        return True
    except Exception:
        return False


def _run_vscode_terminal(command: str, shell: str, cwd: Path) -> str:
    if not _open_vscode_workspace(cwd):
        return "VS Code CLI is not available, so I could not open an integrated terminal there."
    if not _PYAUTOGUI:
        return (
            f"VS Code opened at {cwd}, but PyAutoGUI is not installed so I could not type the command into the integrated terminal."
        )

    time.sleep(1.6)
    _activate_window("Visual Studio Code")
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "shift", "p")
    time.sleep(0.3)
    _paste_or_type("Terminal: Create New Terminal")
    pyautogui.press("enter")
    time.sleep(0.8)
    _paste_or_type(_compose_command(command, shell, cwd))
    pyautogui.press("enter")
    return (
        f"VS Code workspace opened at {cwd} and the command was sent to the integrated terminal.\n"
        f"Command: {_strip_shell_wrapper(command, shell)}"
    )


def _run_visible_terminal(command: str, shell: str, cwd: Path, keep_open: bool = True) -> str:
    platform_name = _get_platform()
    chosen_shell = _normalize_shell(shell, command)
    final_command = _compose_command(command, chosen_shell, cwd)

    try:
        if platform_name == "windows":
            if chosen_shell in {"powershell", "pwsh"}:
                binary = "pwsh.exe" if chosen_shell == "pwsh" and shutil.which("pwsh") else "powershell.exe"
                mode_flag = "-NoExit" if keep_open else "-Command"
                args = [binary, mode_flag, final_command]
                subprocess.Popen(
                    args,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                    cwd=str(cwd),
                )
            elif chosen_shell == "cmd":
                flag = "/k" if keep_open else "/c"
                subprocess.Popen(
                    ["cmd.exe", flag, final_command],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                    cwd=str(cwd),
                )
            else:
                subprocess.Popen(
                    ["bash", "-lc", final_command],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                    cwd=str(cwd),
                )
        elif platform_name == "macos":
            subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{final_command}"'])
        else:
            for term in ("gnome-terminal", "xterm", "konsole"):
                try:
                    subprocess.Popen([term, "--", "bash", "-lc", final_command], cwd=str(cwd))
                    break
                except FileNotFoundError:
                    continue
        return (
            f"{chosen_shell.capitalize()} terminal opened in {cwd}.\n"
            f"Command: {_strip_shell_wrapper(command, chosen_shell)}"
        )
    except Exception as error:
        return f"Terminal open failed: {error}"


def _infer_interaction_mode(task: str, params: dict) -> tuple[bool, bool]:
    task_text = str(task or "").lower()
    open_in_vscode = bool(params.get("open_in_vscode", False)) or any(
        token in task_text for token in ("vs code", "vscode", "visual studio code", "integrated terminal")
    )
    if "visible" in (params or {}):
        visible = bool(params.get("visible"))
    else:
        visible = open_in_vscode or any(
            token in task_text for token in ("terminal", "powershell", "pwsh", "cmd", "console", "shell", "codex")
        )
    return visible, open_in_vscode


def cmd_control(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    task = str(params.get("task", "") or "").strip()
    command = str(params.get("command", "") or "").strip()
    shell = _normalize_shell(str(params.get("shell", "") or "").strip(), command=command)
    timeout = int(params.get("timeout", 30) or 30)
    keep_open = bool(params.get("keep_open", True))
    workdir = _resolve_workdir(
        cwd=str(params.get("cwd", "") or "").strip(),
        task=task,
        command=command,
    )
    visible, open_in_vscode = _infer_interaction_mode(task, params)

    if not task and not command:
        return "Please describe what you want to do."

    if not command:
        hardcoded, hardcoded_shell = _find_hardcoded(task)
        if hardcoded:
            command = hardcoded
            if hardcoded_shell:
                shell = _normalize_shell(hardcoded_shell, command=hardcoded)
            log_event("cmd_control", "hardcoded_command", task[:300], metadata={"command": command[:300], "shell": shell})
        else:
            command = _ask_gemini(task, shell)
            if command == "UNSAFE":
                return "I could not generate a safe terminal command for that request."
            if command.startswith("ERROR:"):
                return f"Could not generate command: {command}"
            log_event("cmd_control", "model_command", task[:300], metadata={"command": command[:300], "shell": shell})

    safe, reason = _is_safe(command)
    if not safe:
        log_event("cmd_control", "blocked", command[:300], metadata={"reason": reason})
        return f"Blocked for safety: {reason}"

    if player:
        player.write_log(f"[CMD/{shell}] {command[:80]}")

    log_event(
        "cmd_control",
        "started",
        command[:500],
        metadata={
            "shell": shell,
            "cwd": str(workdir),
            "visible": bool(visible),
            "open_in_vscode": bool(open_in_vscode),
        },
    )

    if open_in_vscode:
        result = _run_vscode_terminal(command, shell, workdir)
    elif visible:
        result = _run_visible_terminal(command, shell, workdir, keep_open=keep_open)
    else:
        result = _run_silent(command, timeout=timeout, shell=shell, cwd=workdir)

    log_event(
        "cmd_control",
        "finished",
        str(result)[:1000],
        metadata={
            "shell": shell,
            "cwd": str(workdir),
            "visible": bool(visible),
            "open_in_vscode": bool(open_in_vscode),
        },
    )
    return result
