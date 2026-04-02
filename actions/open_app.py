# actions/open_app.py
# AXIOM - Cross-platform app launcher and closer

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import time

try:
    import psutil

    _PSUTIL = True
except ImportError:
    _PSUTIL = False

_APP_ALIASES = {
    "whatsapp": {"Windows": "WhatsApp", "Darwin": "WhatsApp", "Linux": "whatsapp"},
    "chrome": {"Windows": "chrome", "Darwin": "Google Chrome", "Linux": "google-chrome"},
    "google chrome": {"Windows": "chrome", "Darwin": "Google Chrome", "Linux": "google-chrome"},
    "firefox": {"Windows": "firefox", "Darwin": "Firefox", "Linux": "firefox"},
    "spotify": {"Windows": "Spotify", "Darwin": "Spotify", "Linux": "spotify"},
    "vscode": {"Windows": "code", "Darwin": "Visual Studio Code", "Linux": "code"},
    "visual studio code": {"Windows": "code", "Darwin": "Visual Studio Code", "Linux": "code"},
    "discord": {"Windows": "Discord", "Darwin": "Discord", "Linux": "discord"},
    "telegram": {"Windows": "Telegram", "Darwin": "Telegram", "Linux": "telegram"},
    "instagram": {"Windows": "Instagram", "Darwin": "Instagram", "Linux": "instagram"},
    "tiktok": {"Windows": "TikTok", "Darwin": "TikTok", "Linux": "tiktok"},
    "notepad": {"Windows": "notepad.exe", "Darwin": "TextEdit", "Linux": "gedit"},
    "calculator": {"Windows": "calc.exe", "Darwin": "Calculator", "Linux": "gnome-calculator"},
    "terminal": {"Windows": "cmd.exe", "Darwin": "Terminal", "Linux": "gnome-terminal"},
    "cmd": {"Windows": "cmd.exe", "Darwin": "Terminal", "Linux": "bash"},
    "explorer": {"Windows": "explorer.exe", "Darwin": "Finder", "Linux": "nautilus"},
    "file explorer": {"Windows": "explorer.exe", "Darwin": "Finder", "Linux": "nautilus"},
    "paint": {"Windows": "mspaint.exe", "Darwin": "Preview", "Linux": "gimp"},
    "word": {"Windows": "winword", "Darwin": "Microsoft Word", "Linux": "libreoffice --writer"},
    "excel": {"Windows": "excel", "Darwin": "Microsoft Excel", "Linux": "libreoffice --calc"},
    "powerpoint": {"Windows": "powerpnt", "Darwin": "Microsoft PowerPoint", "Linux": "libreoffice --impress"},
    "vlc": {"Windows": "vlc", "Darwin": "VLC", "Linux": "vlc"},
    "zoom": {"Windows": "Zoom", "Darwin": "zoom.us", "Linux": "zoom"},
    "slack": {"Windows": "Slack", "Darwin": "Slack", "Linux": "slack"},
    "steam": {"Windows": "steam", "Darwin": "Steam", "Linux": "steam"},
    "task manager": {"Windows": "taskmgr.exe", "Darwin": "Activity Monitor", "Linux": "gnome-system-monitor"},
    "settings": {"Windows": "ms-settings:", "Darwin": "System Preferences", "Linux": "gnome-control-center"},
    "powershell": {"Windows": "powershell.exe", "Darwin": "Terminal", "Linux": "bash"},
    "edge": {"Windows": "msedge", "Darwin": "Microsoft Edge", "Linux": "microsoft-edge"},
    "brave": {"Windows": "brave", "Darwin": "Brave Browser", "Linux": "brave-browser"},
    "obsidian": {"Windows": "Obsidian", "Darwin": "Obsidian", "Linux": "obsidian"},
    "notion": {"Windows": "Notion", "Darwin": "Notion", "Linux": "notion"},
    "blender": {"Windows": "blender", "Darwin": "Blender", "Linux": "blender"},
    "capcut": {"Windows": "CapCut", "Darwin": "CapCut", "Linux": "capcut"},
    "postman": {"Windows": "Postman", "Darwin": "Postman", "Linux": "postman"},
    "figma": {"Windows": "Figma", "Darwin": "Figma", "Linux": "figma"},
    "mail": {"Windows": "Mail", "Darwin": "Mail", "Linux": "thunderbird"},
    "email": {"Windows": "Mail", "Darwin": "Mail", "Linux": "thunderbird"},
    "outlook": {"Windows": "Outlook", "Darwin": "Microsoft Outlook", "Linux": "thunderbird"},
    "gmail": {"Windows": "Mail", "Darwin": "Mail", "Linux": "thunderbird"},
}

_PROCESS_HINTS = {
    "calculator": ("calculatorapp", "calc"),
    "calc": ("calculatorapp", "calc"),
    "notepad": ("notepad",),
    "chrome": ("chrome",),
    "google chrome": ("chrome",),
    "firefox": ("firefox",),
    "spotify": ("spotify",),
    "vscode": ("code", "code - insiders"),
    "visual studio code": ("code", "code - insiders"),
    "telegram": ("telegram",),
    "mail": ("hxmail", "hxtsr", "mail", "olk", "outlook"),
    "email": ("hxmail", "hxtsr", "mail", "olk", "outlook"),
    "outlook": ("olk", "outlook", "hxmail", "hxtsr"),
}

_WINDOW_TITLE_HINTS = {
    "mail": (" mail", " inbox", "outlook", "gmail", "new outlook"),
    "email": (" mail", " inbox", "outlook", "gmail", "new outlook"),
    "outlook": ("outlook", "inbox", "mail"),
    "gmail": ("gmail", "inbox", "mail"),
    "calculator": ("calculator",),
    "notepad": ("notepad",),
    "telegram": ("telegram",),
    "chrome": ("chrome",),
}

_LAST_WINDOWS_LAUNCHES: dict[str, dict] = {}


def _normalize_token(value: str) -> str:
    return str(value or "").lower().replace(".exe", "").strip()


def _normalize(raw: str) -> str:
    system = platform.system()
    key = _normalize_token(raw)
    if key in _APP_ALIASES:
        return _APP_ALIASES[key].get(system, raw)
    for alias_key, os_map in _APP_ALIASES.items():
        alias_token = _normalize_token(alias_key)
        if alias_token in key or key in alias_token:
            return os_map.get(system, raw)
    return raw


def _is_running(app_name: str) -> bool:
    if not _PSUTIL:
        return True
    app_lower = _normalize_token(app_name).replace(" ", "")
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                proc_name = _normalize_token(proc.info["name"]).replace(" ", "")
                if app_lower in proc_name or proc_name in app_lower:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False


def _process_tokens(raw_name: str, normalized_name: str) -> tuple[str, ...]:
    tokens = {
        _normalize_token(raw_name),
        _normalize_token(normalized_name),
    }
    compact = {token.replace(" ", "") for token in tokens if token}
    tokens.update(compact)
    for key, values in _PROCESS_HINTS.items():
        key_token = _normalize_token(key)
        if key_token in tokens or key_token.replace(" ", "") in compact:
            tokens.update(values)
    return tuple(token for token in tokens if token)


def _title_tokens(raw_name: str, normalized_name: str) -> tuple[str, ...]:
    tokens = {
        _normalize_token(raw_name),
        _normalize_token(normalized_name),
    }
    hints = set()
    for key, values in _WINDOW_TITLE_HINTS.items():
        key_token = _normalize_token(key)
        if key_token in tokens:
            hints.update(values)
    hints.update(token for token in tokens if token and len(token) > 2)
    return tuple(sorted({hint.strip().lower() for hint in hints if hint and len(hint.strip()) > 1}))


def _remember_windows_launch(
    app_name: str,
    normalized_name: str,
    *,
    started_via: str = "",
    start_app_name: str = "",
    start_app_id: str = "",
) -> None:
    record = {
        "raw_name": app_name,
        "normalized_name": normalized_name,
        "started_via": started_via,
        "start_app_name": start_app_name,
        "start_app_id": start_app_id,
        "process_tokens": list(_process_tokens(app_name, normalized_name)),
        "title_tokens": list(_title_tokens(app_name, normalized_name)),
        "timestamp": time.time(),
    }
    keys = {
        _normalize_token(app_name),
        _normalize_token(normalized_name),
    }
    for key in keys:
        if key:
            _LAST_WINDOWS_LAUNCHES[key] = record


def _lookup_windows_launch(app_name: str, normalized_name: str) -> dict:
    keys = (
        _normalize_token(app_name),
        _normalize_token(normalized_name),
    )
    for key in keys:
        if key and key in _LAST_WINDOWS_LAUNCHES:
            return dict(_LAST_WINDOWS_LAUNCHES[key])
    return {}


def _powershell(script: str, timeout: float = 8.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _powershell_json(script: str, timeout: float = 8.0) -> list[dict]:
    try:
        result = _powershell(script, timeout=timeout)
    except Exception:
        return []
    raw = str(result.stdout or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _find_start_apps(app_name: str, normalized_name: str) -> list[dict]:
    labels = []
    for candidate in (app_name, normalized_name):
        text = str(candidate or "").strip()
        if text and text not in labels:
            labels.append(text)

    matches: list[dict] = []
    seen: set[str] = set()
    for label in labels:
        escaped = label.replace("'", "''")
        rows = _powershell_json(
            (
                "$apps = Get-StartApps | Where-Object { "
                f"$_.Name -like '*{escaped}*' -or $_.AppID -like '*{escaped}*' "
                "} | Select-Object -First 8 Name, AppID; "
                "if ($apps) { $apps | ConvertTo-Json -Compress }"
            ),
            timeout=10.0,
        )
        for row in rows:
            app_id = str(row.get("AppID", "") or "").strip()
            if not app_id or app_id in seen:
                continue
            seen.add(app_id)
            matches.append(
                {
                    "name": str(row.get("Name", "") or "").strip(),
                    "app_id": app_id,
                }
            )
    return matches


def _launch_windows_start_app(app_name: str, normalized_name: str) -> bool:
    for row in _find_start_apps(app_name, normalized_name):
        app_id = str(row.get("app_id", "") or "").strip()
        if not app_id:
            continue
        try:
            result = _powershell(
                f"Start-Process 'shell:AppsFolder\\{app_id}'",
                timeout=8.0,
            )
        except Exception:
            continue
        if result.returncode == 0:
            _remember_windows_launch(
                app_name,
                normalized_name,
                started_via="startapps",
                start_app_name=str(row.get("name", "") or ""),
                start_app_id=app_id,
            )
            time.sleep(2.0)
            return True
    return False


def _launch_windows_known_binary(app_name: str, normalized_name: str) -> bool:
    candidates = []
    for candidate in (normalized_name, app_name):
        value = str(candidate or "").strip()
        if value and value not in candidates:
            candidates.append(value)

    for candidate in candidates:
        try:
            if candidate.endswith(":"):
                result = _powershell(f"Start-Process '{candidate}'", timeout=8.0)
                if result.returncode == 0:
                    _remember_windows_launch(app_name, normalized_name, started_via="uri")
                    time.sleep(1.2)
                    return True
                continue

            resolved = shutil.which(candidate) or shutil.which(candidate.lower())
            if resolved or candidate.lower().endswith(".exe"):
                subprocess.Popen(
                    [resolved or candidate],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                _remember_windows_launch(app_name, normalized_name, started_via="binary")
                time.sleep(1.5)
                return True
        except Exception:
            continue
    return False


def _launch_windows(app_name: str, raw_name: str = "") -> bool:
    raw_value = str(raw_name or app_name or "").strip()
    normalized = str(app_name or "").strip()

    if _launch_windows_known_binary(raw_value, normalized):
        return True
    if _launch_windows_start_app(raw_value, normalized):
        return True

    try:
        import pyautogui

        pyautogui.PAUSE = 0.1
        pyautogui.press("win")
        time.sleep(0.6)
        pyautogui.write(raw_value or normalized, interval=0.05)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(3.0)
        _remember_windows_launch(raw_value, normalized, started_via="start_search")
        return True
    except Exception as e:
        print(f"[open_app] Warning: Windows launch failed: {e}")
        return False


def _list_windows() -> list[dict]:
    script = """
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class AxiomWin32 {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
'@;
$rows = New-Object System.Collections.Generic.List[object];
[AxiomWin32]::EnumWindows({
    param($handle, $lparam)
    if ([AxiomWin32]::IsWindowVisible($handle)) {
        $sb = New-Object System.Text.StringBuilder 512
        [void][AxiomWin32]::GetWindowText($handle, $sb, $sb.Capacity)
        $title = $sb.ToString().Trim()
        if ($title) {
            $pid = 0
            [void][AxiomWin32]::GetWindowThreadProcessId($handle, [ref]$pid)
            $rows.Add([pscustomobject]@{
                Handle = $handle.ToInt64()
                Title = $title
                Pid = $pid
            })
        }
    }
    return $true
}, [IntPtr]::Zero) | Out-Null
if ($rows.Count -gt 0) { $rows | ConvertTo-Json -Compress }
"""
    return _powershell_json(script, timeout=10.0)


def _matching_windows(app_name: str, normalized_name: str) -> list[dict]:
    remembered = _lookup_windows_launch(app_name, normalized_name)
    title_tokens = set(_title_tokens(app_name, normalized_name))
    title_tokens.update(str(item).strip().lower() for item in remembered.get("title_tokens", []) if str(item).strip())
    start_app_name = str(remembered.get("start_app_name", "") or "").strip().lower()
    if start_app_name:
        title_tokens.add(start_app_name)

    rows = []
    for row in _list_windows():
        title = str(row.get("Title", "") or "").strip()
        normalized_title = title.lower()
        if any(token in normalized_title for token in title_tokens if token):
            rows.append({"title": title, "pid": int(row.get("Pid", 0) or 0)})
    return rows


def _activate_windows_title(title: str, close_after_focus: bool = False) -> bool:
    escaped = str(title or "").replace("'", "''")
    send_keys = "$shell.SendKeys('%{F4}');" if close_after_focus else ""
    script = (
        f"$title = '{escaped}'; "
        "$shell = New-Object -ComObject WScript.Shell; "
        "if ($shell.AppActivate($title)) { "
        "Start-Sleep -Milliseconds 180; "
        f"{send_keys}"
        "Write-Output 'OK' "
        "} else { Write-Output 'MISS' }"
    )
    try:
        result = _powershell(script, timeout=6.0)
    except Exception:
        return False
    return "OK" in str(result.stdout or "")


def _focus_windows(app_name: str, normalized_name: str) -> bool:
    windows = _matching_windows(app_name, normalized_name)
    for row in windows:
        if _activate_windows_title(str(row.get("title", "") or ""), close_after_focus=False):
            return True
    return False


def _close_windows_by_title(app_name: str, normalized_name: str) -> bool:
    windows = _matching_windows(app_name, normalized_name)
    if not windows:
        return False

    closed_any = False
    seen_titles: set[str] = set()
    for row in windows:
        title = str(row.get("title", "") or "").strip()
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        if _activate_windows_title(title, close_after_focus=True):
            closed_any = True
            time.sleep(0.35)

    if not closed_any:
        return False

    time.sleep(0.6)
    return not bool(_matching_windows(app_name, normalized_name))


def _matching_processes(app_name: str, normalized_name: str) -> list:
    if not _PSUTIL:
        return []

    targets = _process_tokens(app_name, normalized_name)
    matched = []
    for proc in psutil.process_iter(["name"]):
        try:
            proc_name = _normalize_token(proc.info.get("name", "")).replace(" ", "")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if not proc_name:
            continue
        if any(token.replace(" ", "") in proc_name or proc_name in token.replace(" ", "") for token in targets):
            matched.append(proc)

    return matched


def _close_windows_processes(app_name: str, normalized_name: str) -> bool:
    matched = _matching_processes(app_name, normalized_name)

    if not matched:
        return False

    for proc in matched:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    gone, alive = psutil.wait_procs(matched, timeout=4)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return bool(gone or matched)


def _close_windows(app_name: str, normalized_name: str) -> bool:
    if _close_windows_by_title(app_name, normalized_name):
        return True
    if _close_windows_processes(app_name, normalized_name):
        time.sleep(1.0)
        if not _matching_processes(app_name, normalized_name):
            return True
    time.sleep(1.0)
    if _close_windows_processes(app_name, normalized_name):
        time.sleep(1.0)
        if not _matching_processes(app_name, normalized_name):
            return True
    if not _matching_processes(app_name, normalized_name):
        return True
    return False


def _launch_macos(app_name: str) -> bool:
    try:
        result = subprocess.run(["open", "-a", app_name], capture_output=True, timeout=8)
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        result = subprocess.run(["open", "-a", f"{app_name}.app"], capture_output=True, timeout=8)
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        import pyautogui

        pyautogui.hotkey("command", "space")
        time.sleep(0.6)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"[open_app] Warning: macOS Spotlight failed: {e}")
        return False


def _launch_linux(app_name: str) -> bool:
    binary = (
        shutil.which(app_name)
        or shutil.which(app_name.lower())
        or shutil.which(app_name.lower().replace(" ", "-"))
    )
    if binary:
        try:
            subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        subprocess.run(["xdg-open", app_name], capture_output=True, timeout=5)
        return True
    except Exception:
        pass

    try:
        desktop_name = app_name.lower().replace(" ", "-")
        subprocess.run(["gtk-launch", desktop_name], capture_output=True, timeout=5)
        return True
    except Exception:
        pass

    return False


_OS_LAUNCHERS = {
    "Windows": _launch_windows,
    "Darwin": _launch_macos,
    "Linux": _launch_linux,
}

_OS_CLOSERS = {
    "Windows": _close_windows,
}

_OS_FOCUSERS = {
    "Windows": _focus_windows,
}


def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    app_name = str(params.get("app_name", "") or "").strip()
    action = str(params.get("action", "open") or "open").strip().lower()

    if not app_name:
        return "Please specify which application to control, sir."

    system = platform.system()
    launcher = _OS_LAUNCHERS.get(system)
    closer = _OS_CLOSERS.get(system)
    focuser = _OS_FOCUSERS.get(system)

    if action not in {"open", "close", "focus"}:
        return f"Unknown open_app action: {action}"

    if action == "open" and launcher is None:
        return f"Unsupported OS: {system}"
    if action == "close" and closer is None:
        return f"Closing applications is not supported on {system} yet."
    if action == "focus" and focuser is None:
        return f"Focusing applications is not supported on {system} yet."

    normalized = _normalize(app_name)
    verb = {"open": "Launching", "close": "Closing", "focus": "Focusing"}[action]
    print(f"[open_app] {verb}: {app_name} -> {normalized} ({system})")

    if player:
        player.write_log(f"[open_app] {action}: {app_name}")

    try:
        if action == "close":
            success = closer(app_name, normalized)
            if success:
                return f"Closed {app_name} successfully, sir."
            return f"I tried to close {app_name}, sir, but could not confirm it exited."

        if action == "focus":
            success = focuser(app_name, normalized)
            if success:
                return f"Focused {app_name} successfully, sir."
            return f"I tried to focus {app_name}, sir, but could not find a matching window."

        success = launcher(normalized, raw_name=app_name) if system == "Windows" else launcher(normalized)

        if success:
            return f"Opened {app_name} successfully, sir."

        if normalized != app_name:
            success = launcher(app_name, raw_name=app_name) if system == "Windows" else launcher(app_name)
            if success:
                return f"Opened {app_name} successfully, sir."

        return (
            f"I tried to open {app_name}, sir, but couldn't confirm it launched. "
            f"It may still be loading or might not be installed."
        )

    except Exception as e:
        print(f"[open_app] Error: {e}")
        action_word = "close" if action == "close" else "focus" if action == "focus" else "open"
        return f"Failed to {action_word} {app_name}, sir: {e}"
