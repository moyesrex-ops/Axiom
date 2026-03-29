import json
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def prompt_studio(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    medium = str(params.get("medium", "image")).strip().lower()
    idea = str(params.get("idea", "")).strip()
    style = str(params.get("style", "")).strip()
    constraints = str(params.get("constraints", "")).strip()
    target_model = str(params.get("target_model", "")).strip()

    if not idea:
        return "Please describe the concept you want prompts for."

    if speak:
        speak(f"Building {medium} prompts now.")

    from core import gemini_compat as genai

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel("gemini-3.1-pro-preview")

    prompt = f"""You are AXIOM Prompt Studio.
Create elite prompts for {medium} generation.

IDEA:
{idea}

STYLE:
{style or "Use the strongest fitting style direction."}

CONSTRAINTS:
{constraints or "None provided."}

TARGET MODEL:
{target_model or "General high-end image/video model"}

Return a tight but high-value output with these sections:
1. PRIMARY PROMPT
2. VARIATIONS (3)
3. NEGATIVE PROMPT / AVOIDANCES
4. DIRECTOR NOTES
5. OPTIONAL CAMERA / LIGHTING / COMPOSITION NOTES if relevant

Optimize for specificity, texture, mood, framing, and action. Avoid generic filler."""

    response = model.generate_content(prompt)
    result = response.text.strip()

    try:
        from memory.memory_manager import save_to_nexus
        from memory.runtime_store import log_event

        save_to_nexus(f"Prompt Studio: {idea[:60]}", result[:2000])
        log_event("prompt_studio", medium, result[:2000], {"idea": idea[:200]})
    except Exception:
        pass

    return result
