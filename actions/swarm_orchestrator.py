import json
import sys
from pathlib import Path

from core.agent_library import delegate_agent_library, format_agent_delegate_report
from core.runtime_config import load_runtime_config
from core.secret_config import get_gemini_api_key


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()

ROLE_PRESETS = {
    "research": [
        ("Scout", "Find the strongest supporting evidence and useful surface area."),
        ("Skeptic", "Attack weak assumptions, hidden failure modes, and missing evidence."),
        ("Operator", "Focus on concrete execution paths, tools, and sequencing."),
        ("Synthesizer", "Integrate the debate into a practical recommendation."),
    ],
    "strategy": [
        ("Strategist", "Build the strongest plan to win the objective."),
        ("Contrarian", "Challenge consensus and identify asymmetric alternatives."),
        ("Risk Manager", "Focus on downside, constraints, and operational hazards."),
        ("Executor", "Translate strategy into concrete steps."),
    ],
    "build": [
        ("Architect", "Define the best system design."),
        ("Implementer", "Focus on what can actually be built quickly and safely."),
        ("Reviewer", "Find correctness gaps, regressions, and edge cases."),
        ("Operator", "Focus on deployment, runtime behavior, and maintainability."),
    ],
    "critique": [
        ("Advocate", "Defend the current idea as strongly as possible."),
        ("Critic", "Tear apart the current idea and expose flaws."),
        ("Red Team", "Think adversarially about misuse and failure."),
        ("Judge", "Produce the final balanced verdict."),
    ],
}


def _get_api_key() -> str:
    return get_gemini_api_key()


def _run_role(model, role_name: str, instruction: str, goal: str, context: str) -> str:
    prompt = f"""You are {role_name} in AXIOM's multi-agent swarm.
Instruction: {instruction}

GOAL:
{goal}

CONTEXT:
{context or "No extra context provided."}

Deliver a sharp, concrete analysis. End with a one-line VERDICT."""
    response = model.generate_content(prompt)
    return response.text.strip()


def swarm_orchestrator(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    goal = str(params.get("goal", "")).strip()
    mode = str(params.get("mode", "research")).strip().lower()
    context = str(params.get("context", "")).strip()
    query = str(params.get("query", "")).strip()
    agents = params.get("agents")
    limit = int(params.get("limit", 4) or 4)

    if not goal:
        return "Please provide a goal for the swarm."

    if mode in {"specialist", "catalog", "supervised"} or query or agents:
        result = delegate_agent_library(
            task=goal,
            query=query or goal,
            agents=agents,
            limit=limit,
            source_id=str(params.get("source", "") or "").strip().lower(),
            model_name=str(params.get("model", "") or "").strip(),
            context=context,
        )
        report = format_agent_delegate_report(result)
        try:
            from memory.memory_manager import save_to_nexus
            from memory.runtime_store import log_event

            save_to_nexus(f"Swarm Specialists: {goal[:60]}", report[:2000])
            log_event("swarm", "specialist", report[:2000], {"goal": goal[:200]})
        except Exception:
            pass
        return report

    roles = ROLE_PRESETS.get(mode, ROLE_PRESETS["research"])

    if speak:
        speak(f"Launching {len(roles)} swarm agents for {mode}.")

    import google.generativeai as genai

    genai.configure(api_key=_get_api_key())
    runtime = load_runtime_config()
    model = genai.GenerativeModel(
        str((runtime.get("text_models", {}) or {}).get("reasoning", "gemini-2.5-pro") or "gemini-2.5-pro")
    )

    reports = []
    for role_name, instruction in roles:
        reports.append(
            {
                "role": role_name,
                "report": _run_role(model, role_name, instruction, goal, context),
            }
        )

    synthesis_prompt = f"""You are AXIOM's swarm synthesis engine.
Goal: {goal}
Mode: {mode}

AGENT REPORTS:
{json.dumps(reports, indent=2, ensure_ascii=False)}

Produce:
1. Consensus
2. Major disagreements
3. Recommended next moves
4. Final verdict

Be direct and high-signal."""

    final = model.generate_content(synthesis_prompt).text.strip()
    report_text = "\n\n".join(
        [f"== {item['role'].upper()} ==\n{item['report']}" for item in reports]
    )
    result = f"{report_text}\n\n== SWARM CONSENSUS ==\n{final}"

    try:
        from memory.memory_manager import save_to_nexus
        from memory.runtime_store import log_event

        save_to_nexus(f"Swarm: {goal[:60]}", result[:2000])
        log_event("swarm", mode, result[:2000], {"goal": goal[:200]})
    except Exception:
        pass

    return result
