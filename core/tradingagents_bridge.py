import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path

from core.runtime_config import load_runtime_config, update_runtime_config
from core.secret_config import get_secret


DEFAULT_ANALYSTS = ["market", "social", "news", "fundamentals"]


def configure_tradingagents(updates: dict) -> dict:
    return update_runtime_config({"tradingagents": updates or {}})


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def _tradingagents_config() -> dict:
    return load_runtime_config().get("tradingagents", {}) or {}


def _path_or_none(value: str | Path | None) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _candidate_repo_paths() -> list[Path]:
    configured = _path_or_none(_tradingagents_config().get("repo_path", ""))
    return [
        path
        for path in [
            configured,
            Path.home() / "Axiom_research" / "external" / "TradingAgents",
        ]
        if path is not None
    ]


def resolve_tradingagents_repo_path() -> Path | None:
    for candidate in _candidate_repo_paths():
        try:
            if candidate.exists() and (candidate / "README.md").exists() and (candidate / "pyproject.toml").exists():
                return candidate
        except Exception:
            continue
    return None


def _venv_python(repo_path: Path | None) -> Path | None:
    if repo_path is None:
        return None
    candidates = [
        repo_path / ".venv" / "Scripts" / "python.exe",
        repo_path / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _read_text(path: Path, limit: int = 1200) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit].strip()
    except Exception:
        return ""


def _read_pyproject(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _run_command(command: list[str], cwd: Path | None = None, env: dict | None = None, timeout: int = 30) -> dict:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except Exception as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "output": str(exc),
        }

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    output = "\n".join(part for part in [stdout, stderr] if part).strip()
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "output": output,
    }


def _results_root(repo_path: Path | None) -> Path | None:
    if repo_path is None:
        return None
    return repo_path / "eval_results"


def _run_files(repo_path: Path | None) -> list[Path]:
    root = _results_root(repo_path)
    if root is None or not root.exists():
        return []
    rows = sorted(
        [path for path in root.glob("*/*/full_states_log_*.json") if path.is_file()],
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )
    return rows


def _extract_run_summary(path: Path) -> dict:
    payload = {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        payload = {}

    trade_date = ""
    state = {}
    if isinstance(payload, dict) and payload:
        trade_date, state = next(reversed(list(payload.items())))
        if not isinstance(state, dict):
            state = {}

    ticker = str(state.get("company_of_interest", "") or path.parents[1].name).strip()
    final_decision = str(state.get("final_trade_decision", "") or "").strip()
    investment_plan = str(state.get("investment_plan", "") or "").strip()
    return {
        "ticker": ticker,
        "trade_date": str(state.get("trade_date", "") or trade_date).strip(),
        "path": str(path),
        "final_trade_decision": final_decision[:220],
        "investment_plan": investment_plan[:220],
    }


def list_tradingagents_runs(limit: int = 5) -> list[dict]:
    repo_path = resolve_tradingagents_repo_path()
    rows = []
    for path in _run_files(repo_path)[: max(int(limit), 1)]:
        rows.append(_extract_run_summary(path))
    return rows


def _package_meta(repo_path: Path | None) -> tuple[str, str]:
    if repo_path is None:
        return "", ""
    payload = _read_pyproject(repo_path / "pyproject.toml")
    project = payload.get("project", {}) if isinstance(payload, dict) else {}
    return (
        str(project.get("name", "") or "").strip(),
        str(project.get("version", "") or "").strip(),
    )


def _count_role_files(repo_path: Path | None) -> int:
    if repo_path is None:
        return 0
    agents_root = repo_path / "tradingagents" / "agents"
    if not agents_root.exists():
        return 0
    return sum(
        1
        for path in agents_root.rglob("*.py")
        if path.is_file() and path.name != "__init__.py" and "utils" not in path.parts
    )


def _venv_import_ready(repo_path: Path | None) -> tuple[bool, str]:
    python_path = _venv_python(repo_path)
    if python_path is None:
        return False, "Virtual environment not prepared."

    result = _run_command(
        [str(python_path), "-c", "import tradingagents, langgraph, yfinance; print('ready')"],
        cwd=repo_path,
        timeout=25,
    )
    if result["ok"] and "ready" in result["stdout"]:
        return True, "ready"
    return False, result["output"][:240] or "Import check failed."


def collect_tradingagents_status(limit: int = 5) -> dict:
    repo_path = resolve_tradingagents_repo_path()
    package_name, package_version = _package_meta(repo_path)
    import_ready, import_message = _venv_import_ready(repo_path)
    runs = list_tradingagents_runs(limit=limit)
    cfg = _tradingagents_config()
    python_path = _venv_python(repo_path)

    return {
        "repo_path": str(repo_path) if repo_path else "",
        "package_name": package_name,
        "package_version": package_version,
        "uv_available": bool(shutil.which("uv")),
        "venv_python": str(python_path) if python_path else "",
        "venv_ready": python_path is not None,
        "import_ready": import_ready,
        "import_message": import_message,
        "role_count": _count_role_files(repo_path),
        "results_root": str(_results_root(repo_path)) if repo_path else "",
        "runs_count": len(_run_files(repo_path)),
        "recent_runs": runs,
        "provider": str(cfg.get("provider", "google") or "google"),
        "deep_think_llm": str(cfg.get("deep_think_llm", "") or ""),
        "quick_think_llm": str(cfg.get("quick_think_llm", "") or ""),
        "default_analysts": list(cfg.get("default_analysts", DEFAULT_ANALYSTS) or DEFAULT_ANALYSTS),
        "max_debate_rounds": int(cfg.get("max_debate_rounds", 1) or 1),
        "max_risk_discuss_rounds": int(cfg.get("max_risk_discuss_rounds", 1) or 1),
    }


def format_tradingagents_status(limit: int = 5) -> str:
    status = collect_tradingagents_status(limit=limit)
    lines = [
        "TradingAgents integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"Package: {status['package_name'] or 'unknown'} {status['package_version'] or ''}".strip(),
        f"uv available: {'yes' if status['uv_available'] else 'no'}",
        f"Sidecar venv ready: {'yes' if status['venv_ready'] else 'no'}",
        f"Package import ready: {'yes' if status['import_ready'] else 'no'}",
        f"Import check: {status['import_message'] or 'n/a'}",
        f"Role modules detected: {status['role_count']}",
        f"Logged runs: {status['runs_count']}",
        f"Configured provider: {status['provider']}",
        f"Configured deep model: {status['deep_think_llm'] or 'auto'}",
        f"Configured quick model: {status['quick_think_llm'] or 'auto'}",
        f"Default analysts: {', '.join(status['default_analysts'])}",
    ]
    if status["recent_runs"]:
        lines.append("Recent runs:")
        for row in status["recent_runs"]:
            lines.append(
                f"- {row['ticker']} @ {row['trade_date']} | decision={row['final_trade_decision'] or 'n/a'}"
            )
    return "\n".join(lines)


def tradingagents_launch_instructions() -> str:
    status = collect_tradingagents_status(limit=3)
    repo_path = status["repo_path"]
    if not repo_path:
        return (
            "TradingAgents repo path is not configured. Set tradingagents.repo_path or place the repo at "
            "C:/Users/moyes/Axiom_research/external/TradingAgents."
        )

    if not status["uv_available"]:
        return (
            "TradingAgents is cloned, but uv is not available. Install uv first, then run:\n"
            f"Set-Location '{repo_path}'; uv sync --python 3.12"
        )

    if not status["venv_ready"] or not status["import_ready"]:
        return (
            "TradingAgents needs its sidecar environment prepared. Run:\n"
            f"Set-Location '{repo_path}'; uv sync --python 3.12"
        )

    return (
        "TradingAgents is ready as a sidecar trading-analysis runtime. Typical commands:\n"
        f"Set-Location '{repo_path}'; uv run python -m unittest discover -s tests -p \"test_*.py\" -v\n"
        f"Set-Location '{repo_path}'; uv run python -c \"from tradingagents.graph.trading_graph import TradingAgentsGraph; from tradingagents.default_config import DEFAULT_CONFIG; print(DEFAULT_CONFIG['llm_provider'])\""
    )


def prepare_tradingagents_repo(timeout: int = 1800) -> dict:
    repo_path = resolve_tradingagents_repo_path()
    if repo_path is None:
        return {"prepared": False, "message": "TradingAgents repo was not found."}
    if not shutil.which("uv"):
        return {"prepared": False, "message": "uv is not installed on this machine."}

    result = _run_command(["uv", "sync", "--python", "3.12"], cwd=repo_path, timeout=timeout)
    post = collect_tradingagents_status(limit=3)
    prepared = bool(post["venv_ready"] and post["import_ready"])
    return {
        "prepared": prepared and result["ok"],
        "message": (
            "TradingAgents sidecar environment is ready."
            if prepared and result["ok"]
            else result["output"][:500] or "TradingAgents prepare failed."
        ),
        "output_excerpt": result["output"][:1500],
        "venv_ready": post["venv_ready"],
        "import_ready": post["import_ready"],
    }


def _normalize_analysts(value) -> list[str]:
    if isinstance(value, list):
        rows = [str(item).strip().lower() for item in value if str(item).strip()]
    elif isinstance(value, str):
        rows = [part.strip().lower() for part in value.split(",") if part.strip()]
    else:
        rows = []
    return rows or list(DEFAULT_ANALYSTS)


def _provider_env(provider: str) -> dict:
    env = dict(os.environ)
    provider = str(provider or "google").strip().lower()
    if provider == "google":
        key = get_secret("gemini_api_key", ["GOOGLE_API_KEY", "GEMINI_API_KEY"])
        if key:
            env["GOOGLE_API_KEY"] = key
    elif provider == "openai":
        key = get_secret("openai_api_key", ["OPENAI_API_KEY"])
        if key:
            env["OPENAI_API_KEY"] = key
    elif provider == "anthropic":
        key = get_secret("anthropic_api_key", ["ANTHROPIC_API_KEY"])
        if key:
            env["ANTHROPIC_API_KEY"] = key
    elif provider == "xai":
        key = get_secret("xai_api_key", ["XAI_API_KEY"])
        if key:
            env["XAI_API_KEY"] = key
    elif provider == "openrouter":
        key = get_secret("openrouter_api_key", ["OPENROUTER_API_KEY"])
        if key:
            env["OPENROUTER_API_KEY"] = key
    return env


def _extract_json_line(output: str) -> dict | None:
    for raw_line in reversed(str(output or "").splitlines()):
        line = raw_line.strip()
        if not line.startswith("{") or not line.endswith("}"):
            continue
        try:
            payload = json.loads(line)
            return payload if isinstance(payload, dict) else None
        except Exception:
            continue
    return None


def _extract_json_object(text: str) -> dict:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        pass

    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _normalize_confidence(value) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 0.0 <= numeric <= 1.0:
        numeric *= 100.0
    return max(0.0, min(numeric, 100.0))


def _external_market_context_block(ticker: str) -> tuple[str, dict]:
    sections = []
    meta = {"crucix_used": False, "mirofish_used": False}

    try:
        from core.crucix_bridge import format_crucix_market_context

        crucix_block = format_crucix_market_context(ticker, limit=4)
        if "unavailable" not in crucix_block.lower():
            sections.append("[Crucix Live Context]\n" + crucix_block)
            meta["crucix_used"] = True
    except Exception as error:
        meta["crucix_error"] = str(error)[:240]

    try:
        from core.mirofish_bridge import format_mirofish_market_context

        mirofish_block = format_mirofish_market_context(ticker, limit=4)
        if "unavailable" not in mirofish_block.lower():
            sections.append("[MiroFish Context]\n" + mirofish_block)
            meta["mirofish_used"] = True
    except Exception as error:
        meta["mirofish_error"] = str(error)[:240]

    return "\n\n".join(section for section in sections if section).strip(), meta


def _fuse_market_intelligence(result: dict, context_block: str) -> dict:
    if not context_block.strip():
        return {}

    api_key = get_secret("gemini_api_key", ["GOOGLE_API_KEY", "GEMINI_API_KEY"])
    if not api_key:
        return {}

    try:
        import google.generativeai as genai

        runtime = load_runtime_config()
        text_models = runtime.get("text_models", {}) or {}
        model_name = (
            str(text_models.get("fast", "") or "").strip()
            or str(text_models.get("default", "") or "").strip()
            or "gemini-2.5-flash"
        )
        prompt = (
            "You are fusing TradingAgents output with live external market context.\n"
            "Return strict JSON only.\n"
            '{"action":"buy|sell|hold|avoid","confidence":0,"reason":"short rationale","stop_loss":null,"take_profit":null,"summary":"short fused summary"}\n'
            "Use BUY or SELL only when the combined evidence is coherent. If the signals conflict, use HOLD or AVOID.\n"
            "Only include stop_loss and take_profit when they are explicitly justified by the analysis; otherwise use null.\n\n"
            f"[TRADINGAGENTS RESULT]\n{json.dumps(result, ensure_ascii=False)}\n\n"
            f"{context_block}"
        )
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        payload = _extract_json_object(getattr(response, "text", "") or "")
        if not payload:
            return {}
        return {
            "fusion_action": str(payload.get("action", "") or "").strip().lower(),
            "fusion_confidence": _normalize_confidence(payload.get("confidence", 0.0) or 0.0),
            "fusion_reason": str(payload.get("reason", "") or "").strip(),
            "fusion_stop_loss": payload.get("stop_loss"),
            "fusion_take_profit": payload.get("take_profit"),
            "fusion_summary": str(payload.get("summary", "") or "").strip(),
        }
    except Exception:
        return {}


def run_tradingagents_analysis(parameters: dict | None = None) -> dict:
    params = parameters or {}
    repo_path = resolve_tradingagents_repo_path()
    if repo_path is None:
        return {"ok": False, "message": "TradingAgents repo was not found."}

    python_path = _venv_python(repo_path)
    if python_path is None:
        return {"ok": False, "message": "TradingAgents sidecar environment is not prepared yet."}

    runtime = load_runtime_config()
    cfg = _tradingagents_config()
    text_models = runtime.get("text_models", {}) or {}
    ticker = str(params.get("ticker", "") or params.get("asset", "") or "").strip().upper()
    if not ticker:
        return {"ok": False, "message": "Please provide a ticker."}

    trade_date = str(params.get("trade_date", "") or date.today().isoformat()).strip()
    provider = str(params.get("provider", "") or cfg.get("provider", "google") or "google").strip().lower()
    deep_model = str(
        params.get("deep_model", "")
        or cfg.get("deep_think_llm", "")
        or text_models.get("reasoning", "gemini-2.5-pro")
        or "gemini-2.5-pro"
    ).strip()
    quick_model = str(
        params.get("quick_model", "")
        or cfg.get("quick_think_llm", "")
        or text_models.get("fast", "gemini-2.5-flash-lite")
        or "gemini-2.5-flash-lite"
    ).strip()
    analysts = _normalize_analysts(params.get("analysts", cfg.get("default_analysts", DEFAULT_ANALYSTS)))
    max_debate_rounds = int(params.get("max_debate_rounds", cfg.get("max_debate_rounds", 1)) or 1)
    max_risk_rounds = int(params.get("max_risk_discuss_rounds", cfg.get("max_risk_discuss_rounds", 1)) or 1)
    timeout = int(params.get("timeout", 1800) or 1800)

    env = _provider_env(provider)
    if provider == "google" and not env.get("GOOGLE_API_KEY"):
        return {"ok": False, "message": "Gemini/Google API key is missing for TradingAgents."}

    payload = {
        "ticker": ticker,
        "trade_date": trade_date,
        "provider": provider,
        "deep_model": deep_model,
        "quick_model": quick_model,
        "analysts": analysts,
        "max_debate_rounds": max_debate_rounds,
        "max_risk_discuss_rounds": max_risk_rounds,
    }

    script = r"""
import json
import sys

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

payload = json.loads(sys.argv[1])
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = payload["provider"]
config["deep_think_llm"] = payload["deep_model"]
config["quick_think_llm"] = payload["quick_model"]
config["max_debate_rounds"] = payload["max_debate_rounds"]
config["max_risk_discuss_rounds"] = payload["max_risk_discuss_rounds"]
config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
    "news_data": "yfinance",
}
config["tool_vendors"] = {}

graph = TradingAgentsGraph(
    selected_analysts=payload["analysts"],
    debug=False,
    config=config,
)
final_state, decision = graph.propagate(payload["ticker"], payload["trade_date"])
result = {
    "ticker": payload["ticker"],
    "trade_date": payload["trade_date"],
    "provider": payload["provider"],
    "deep_model": payload["deep_model"],
    "quick_model": payload["quick_model"],
    "analysts": payload["analysts"],
    "decision": str(decision or "").strip(),
    "final_trade_decision": str(final_state.get("final_trade_decision", "") or "").strip(),
    "investment_plan": str(final_state.get("investment_plan", "") or "").strip(),
    "trader_investment_plan": str(final_state.get("trader_investment_plan", "") or "").strip(),
    "market_report": str(final_state.get("market_report", "") or "").strip(),
    "sentiment_report": str(final_state.get("sentiment_report", "") or "").strip(),
    "news_report": str(final_state.get("news_report", "") or "").strip(),
    "fundamentals_report": str(final_state.get("fundamentals_report", "") or "").strip(),
}
print(json.dumps(result, ensure_ascii=False))
"""
    result = _run_command(
        [str(python_path), "-c", script, json.dumps(payload, ensure_ascii=False)],
        cwd=repo_path,
        env=env,
        timeout=timeout,
    )
    parsed = _extract_json_line(result["stdout"] or result["output"])
    if not result["ok"] or parsed is None:
        return {
            "ok": False,
            "message": result["output"][:800] or "TradingAgents analysis failed.",
            "output_excerpt": result["output"][:2500],
        }

    run_file = ""
    matching = [
        row
        for row in list_tradingagents_runs(limit=12)
        if row.get("ticker", "").upper() == ticker and row.get("trade_date", "") == trade_date
    ]
    if matching:
        run_file = matching[0].get("path", "")

    final_result = {
        "ok": True,
        "ticker": ticker,
        "trade_date": trade_date,
        "provider": provider,
        "deep_model": deep_model,
        "quick_model": quick_model,
        "analysts": analysts,
        "decision": parsed.get("decision", ""),
        "final_trade_decision": parsed.get("final_trade_decision", ""),
        "investment_plan": parsed.get("investment_plan", ""),
        "trader_investment_plan": parsed.get("trader_investment_plan", ""),
        "market_report": parsed.get("market_report", ""),
        "sentiment_report": parsed.get("sentiment_report", ""),
        "news_report": parsed.get("news_report", ""),
        "fundamentals_report": parsed.get("fundamentals_report", ""),
        "run_file": run_file,
        "output_excerpt": result["output"][:1200],
    }
    external_context, external_meta = _external_market_context_block(ticker)
    final_result["external_context"] = external_context
    final_result["external_context_meta"] = external_meta
    final_result.update(_fuse_market_intelligence(final_result, external_context))
    return final_result


def format_tradingagents_analysis(result: dict) -> str:
    if not result.get("ok"):
        return str(result.get("message", "TradingAgents analysis failed."))

    lines = [
        f"TradingAgents analysis: {result['ticker']} @ {result['trade_date']}",
        f"Provider: {result['provider']}",
        f"Deep model: {result['deep_model']}",
        f"Quick model: {result['quick_model']}",
        f"Analysts: {', '.join(result.get('analysts', []))}",
        f"Decision: {result.get('decision', '') or 'n/a'}",
    ]
    if result.get("final_trade_decision"):
        lines.append(f"Final trade decision: {result['final_trade_decision'][:500]}")
    if result.get("investment_plan"):
        lines.append(f"Investment plan: {result['investment_plan'][:500]}")
    if result.get("trader_investment_plan"):
        lines.append(f"Trader plan: {result['trader_investment_plan'][:500]}")
    if result.get("fusion_summary"):
        lines.append(f"Live context fusion: {result['fusion_summary'][:500]}")
    if result.get("fusion_action"):
        lines.append(
            f"Fused action: {result['fusion_action']}"
            + (
                f" | confidence={result['fusion_confidence']:.1f}%"
                if result.get("fusion_confidence") not in (None, "")
                else ""
            )
        )
    if result.get("run_file"):
        lines.append(f"Run log: {result['run_file']}")
    return "\n".join(lines)
