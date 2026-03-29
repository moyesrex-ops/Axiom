import json
import re
import sys
from pathlib import Path

from core.secret_config import get_gemini_api_key
from memory.runtime_store import log_event, search_knowledge_items

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
PLANNER_PROMPT = """You are the planning module of AXIOM, a personal AI assistant.
Your job: break any user goal into a sequence of steps using ONLY the tools listed below.

ABSOLUTE RULES:
- NEVER use generated_code.
- Use codex_builder for runnable multi-file projects, playable games, websites, apps, or when the user needs a real artifact they can open.
- Use code_helper for single-file scripts, focused edits, explanations, and small code tasks.
- Never use codex_builder, code_helper, or dev_agent for market analysis, trading decisions, MT5 execution, or general research unless the user explicitly asked to build software or write code.
- For complex build, research, debugging, review, or orchestration tasks, strongly consider skill_library and agent_library early so AXIOM can use specialist workflows and delegated analysis automatically.
- Use deerflow_control when DeerFlow is live and the task benefits from a deeper super-agent harness with planning/subagents.
- NEVER reference previous step results in parameters. Every step is independent.
- Use web_search for ANY information retrieval, research, or current data.
- Use system_capabilities if the task depends on installed integrations or current environment status.
- Use memory_archive when the task depends on saved preferences, archived instructions, or earlier durable knowledge.
- Use skill_library when you need an external workflow, coding pattern, debugging checklist, testing playbook, planning-with-files workflow, or last30days-style recent research workflow.
- Use agent_library when the task needs specialist roles, delegated review, OpenManus-style orchestration guidance, or supervisor-style multi-agent execution.
- Use self_modifier when the user asks AXIOM to change its own voice, add/edit tools, or modify its own behavior.
- Use persona_control when the task is specifically about PersonaPlex status or configuration.
- Use lightpanda_control when the task depends on an optional Lightpanda browser backend.
- Use autoresearch_control when the task depends on the local autoresearch repo, program.md, or experiment log.
- Use dexter_control for the imported Dexter financial research runtime and status.
- Use pentagi_control for the imported PentAGI security runtime status and limitations.
- Use tradingagents_control when the task depends on the imported TradingAgents runtime, trading runs, or multi-agent market analysis.
- Use paperclip_control, openfang_control, symphony_control, or lossless_claw_control when the task is specifically about those imported repos or their runtime readiness.
- Use crucix_control for the Crucix intelligence engine, live OSINT/market sweeps, or briefing-style world intelligence.
- Use file_controller to save content to disk.
- Use cmd_control to open files or run system commands.
- Max 5 steps. Use the minimum steps needed.

AVAILABLE TOOLS AND THEIR PARAMETERS:

open_app
  app_name: string (required)

web_search
  query: string (required) — write a clear, focused search query
  mode: "search" | "compare" | "deep" | "social" (optional, default: search)
  items: list of strings (optional, for compare mode)
  aspect: string (optional, for compare mode)
  context: string (optional, extra guidance for deep/social search)
  sources: list of strings (optional, for deep search: web | discussions | academic)

browser_control
  action: "go_to" | "search" | "click" | "type" | "scroll" | "fill_form" | "smart_click" | "smart_type" | "get_text" | "press" | "current_state" | "close_tab" | "youtube_play" | "close" (required)
  url: string (for go_to)
  query: string (for search)
  kind: "video" | "shorts" | "auto" (for youtube_play)
  selector: string (for click/type)
  text: string (for click/type)
  description: string (for smart_click/smart_type)
  direction: "up" | "down" (for scroll)
  key: string (for press)

file_controller
  action: "write" | "create_file" | "read" | "list" | "delete" | "move" | "copy" | "find" | "disk_usage" (required)
  path: string — use "desktop" for Desktop folder
  name: string — filename
  content: string — file content (for write/create_file)

cmd_control
  task: string (optional) — natural language description of what to do
  command: string (optional) — exact shell command when already known
  shell: "auto" | "powershell" | "pwsh" | "cmd" | "bash" (optional)
  cwd: string (optional) — path or shortcut such as repo | workspace | home | desktop
  visible: boolean (optional)
  open_in_vscode: boolean (optional)
  keep_open: boolean (optional)
  timeout: integer (optional)

computer_settings
  action: string (required)
  description: string — natural language description
  value: string (optional)
  note: use hardware_status / gpu_status / open_device_manager for hardware inspection or device access

computer_control
  action: "type" | "click" | "hotkey" | "press" | "scroll" | "screenshot" | "screen_find" | "screen_click" (required)
  text: string (for type)

reminder
  date: string YYYY-MM-DD (required)
  time: string HH:MM (required)
  message: string (required)

desktop_control
  action: "wallpaper" | "organize" | "clean" | "list" | "task" (required)
  path: string (optional)
  task: string (optional)

youtube_video
  action: "play" | "summarize" | "get_info" | "trending" | "state" (required)
  query: string (for play)
  url: string (for play/get_info/summarize)
  kind: "video" | "shorts" | "auto" (for play)
  region: string (for trending)
  save: boolean (for summarize)

weather_report
  city: string (required)

flight_finder
  origin: string (required)
  destination: string (required)
  date: string (required)

code_helper
  action: "write" | "edit" | "run" | "explain" (required)
  description: string (required)
  language: string (optional)
  output_path: string (optional)
  file_path: string (optional)

dev_agent
  description: string (required)
  language: string (optional)

codex_builder
  action: "build" | "status" (required)
  description: string (required for build)
  project_name: string (optional)
  project_path: string (optional)
  model: string (optional)
  timeout: integer (optional)
  open_when_done: boolean (optional)

self_modifier
  action: "read_source" | "write_action" | "edit_action" | "generate_action" | "list_actions" | "change_voice" | "list_voices" (required)
  file_path: string (optional)
  tool_name: string (optional)
  description: string (optional)
  code: string (optional)
  new_code: string (optional)
  voice_name: string (optional)

system_capabilities
  action: "summary" | "status" | "doctor" | "context" | "operator" | "routing" | "hardware" | "integrations" | "mirofish" | "automaton" | "dexter" | "pentagi" | "tradingagents" | "lightpanda" | "autoresearch" | "deerflow" | "crucix" | "learning" | "paperclip" | "openfang" | "symphony" | "lossless_claw" | "skills" | "agents" | "failures" | "events" | "tasks" (optional)
  limit: integer (optional)

memory_archive
  action: "save" | "recall" | "list" | "recent" | "search" (required)
  topic: string (for save/recall)
  content: string (for save)
  query: string (for search)
  limit: integer (optional)

deep_analyzer
  query: string (optional)
  topic: string (optional)
  scope: string (optional)
  angle: string (optional)
  save: boolean (optional)

autonomous_researcher
  topic: string (required)
  depth: string (optional)
  objective: string (optional)
  format: string (optional)
  save: boolean (optional)

mt5_trading
  action: string (required)
  symbol: string (optional)
  volume: number (optional)
  side: string (optional)
  stop_loss: number (optional)
  take_profit: number (optional)
  note: string (optional)

computer_use
  action: "observe" | "analyze" | "read_text" | "find" | "find_and_click" | "find_and_type" | "verify" | "screenshot" | "move" | "click" | "type" | "hotkey" | "info" (required)
  description: string (for find/find_and_click/find_and_type/verify/observe)
  question: string (optional question for observe/find)
  expected: string (for verify)
  x: integer (for move)
  y: integer (for move)
  button: "left" | "right" | "middle" (for click)
  clicks: integer (for click)
  text: string (for type/find_and_type)
  clear_first: boolean (for find_and_type)
  source: "screen" | "camera" (optional for observe/find)
  keys: list[string] (for hotkey)


skill_library
  action: "status" | "sources" | "search" | "recommend" | "read" (optional)
  query: string (for search)
  task: string (for recommend)
  skill: string (for read)
  source: string (optional)
  limit: integer (optional)
  content_limit: integer (optional)

agent_library
  action: "status" | "sources" | "search" | "recommend" | "read" | "delegate" (optional)
  query: string (for search/delegate)
  task: string (for recommend/delegate)
  agent: string (for read)
  agents: list[string] or comma-separated string (for delegate)
  source: string (optional)
  limit: integer (optional)
  model: string (optional)
  context: string (optional)

dexter_control
  action: "status" | "configure" | "launch_instructions" (required)
  repo_path: string (optional)

pentagi_control
  action: "status" | "configure" | "launch_instructions" (required)
  repo_path: string (optional)

tradingagents_control
  action: "status" | "runs" | "configure" | "prepare" | "analyze" | "execute_mt5" | "launch_instructions" (required)
  repo_path: string (optional)
  ticker: string (for analyze)
  trade_date: string YYYY-MM-DD (for analyze)
  provider: string (optional)
  deep_model: string (optional)
  quick_model: string (optional)
  analysts: list[string] (optional)
  max_debate_rounds: integer (optional)
  max_risk_discuss_rounds: integer (optional)
  timeout: integer (optional)
  limit: integer (optional)
  symbol: string (optional, MT5 symbol override for execute_mt5)
  volume: number (optional, default 0.01 for execute_mt5)
  confirm: boolean (optional, required for live execute_mt5)
  dry_run: boolean (optional)
  min_confidence: integer (optional)
  max_volume: number (optional)
  allowed_symbols: list[string] (optional)

lightpanda_control
  action: "status" | "endpoint" | "configure" | "launch_instructions" (required)
  backend: "playwright" | "lightpanda" (optional)
  endpoint: string (optional)
  repo_path: string (optional)
  auto_connect: boolean (optional)

autoresearch_control
  action: "status" | "program" | "results" | "configure" | "launch_instructions" (required)
  repo_path: string (optional)
  limit: integer (optional)
  content_limit: integer (optional)
  save: boolean (optional)

deerflow_control
  action: "status" | "configure" | "prepare" | "start" | "query" | "launch_instructions" (required)
  prompt: string (for query)
  query: string (for query)
  goal: string (for query)
  mode: "flash" | "standard" | "pro" | "ultra" (optional)
  thread_id: string (optional)
  timeout: integer (optional)

paperclip_control
  action: "status" | "configure" | "launch_instructions" (required)
  repo_path: string (optional)
  api_url: string (optional)
  auto_start: boolean (optional)

openfang_control
  action: "status" | "configure" | "launch_instructions" (required)
  repo_path: string (optional)
  dashboard_url: string (optional)
  auto_start: boolean (optional)

symphony_control
  action: "status" | "configure" | "launch_instructions" (required)
  repo_path: string (optional)
  workflow_path: string (optional)

lossless_claw_control
  action: "status" | "configure" | "launch_instructions" (required)
  repo_path: string (optional)
  database_path: string (optional)

crucix_control
  action: "status" | "configure" | "brief" | "ideas" | "start" | "launch_instructions" (required)
  repo_path: string (optional)
  api_url: string (optional)
  auto_start: boolean (optional)
  timeout: integer (optional)

predict_market
  asset: string (required)
  context: string (optional)
  source: "auto" | "axiom" | "mirofish" | "tradingagents" (optional)
  trade_date: string YYYY-MM-DD (optional)
  provider: string (optional)
  deep_model: string (optional)
  quick_model: string (optional)
  analysts: list[string] (optional)

mirofish_control
  action: "status" | "projects" | "simulations" | "reports" | "market_seed" | "configure" | "start_backend" | "launch_instructions" (required)
  asset: string (for market_seed)
  repo_path: string (optional)
  server_url: string (optional)
  auto_start: boolean (optional)
  limit: integer (optional)

automaton_control
  action: "status" | "memory" | "state" | "soul" | "configure" | "start_runtime" | "launch_instructions" (required)
  repo_path: string (optional)
  state_dir: string (optional)
  auto_start: boolean (optional)
  limit: integer (optional)

persona_control
  action: "status" | "enable" | "disable" | "configure" | "launch_instructions" (required)
  server_url: string (optional)
  repo_path: string (optional)
  text_prompt: string (optional)
  voice_prompt: string (optional)
  cpu_offload: boolean (optional)
  auto_start: boolean (optional)

prompt_studio
  idea: string (required)
  medium: string (optional)
  style: string (optional)
  constraints: string (optional)

lead_researcher
  query: string (optional)
  industry: string (optional)
  location: string (optional)
  site: string (optional)
  max_results: integer (optional)

swarm_orchestrator
  goal: string (required)
  mode: "research" | "strategy" | "build" | "critique" | "specialist" (optional)
  context: string (optional)
  query: string (optional, for specialist mode)
  agents: list[string] or comma-separated string (optional, for specialist mode)
  source: string (optional)
  limit: integer (optional)
  model: string (optional)

EXAMPLES:

Goal: "research machine learning and save to a file"
Steps:
  1. web_search | query: "machine learning overview definition history"
  2. web_search | query: "machine learning applications and future trends"
  3. file_controller | action: write, path: desktop, name: machine_learning.txt, content: "MACHINE LEARNING RESEARCH\\n\\nThis file will be filled with web research results."
  4. cmd_control | task: "open machine_learning.txt on desktop with notepad"

Goal: "What is the Bitcoin price"
Steps:
  1. web_search | query: "Bitcoin price today USD"

Goal: "List desktop files and find the 5 largest"
Steps:
  1. file_controller | action: list, path: desktop
  2. file_controller | action: largest, path: desktop, count: 5

OUTPUT — return ONLY valid JSON, no markdown, no explanation, no code blocks:
{
  "goal": "...",
  "steps": [
    {
      "step": 1,
      "tool": "tool_name",
      "description": "what this step does",
      "parameters": {},
      "critical": true
    }
  ]
}
"""


def _get_api_key() -> str:
    return get_gemini_api_key()


_VAGUE_WORDS = {
    "a", "an", "the", "some", "something", "nice", "good", "cool",
    "interesting", "random", "any", "stuff", "thing", "things",
    "whatever", "anything", "play", "search", "find", "show",
    "me", "just", "do", "make", "get", "it", "that", "this",
    "for", "on", "youtube", "video", "videos", "watch", "open",
    "look", "up", "about", "please", "can", "you", "would",
}


def _goal_is_vague(goal: str) -> bool:
    """Detect if a goal is too generic/vague to produce good results."""
    tokens = re.findall(r"[a-z0-9']+", str(goal or "").lower())
    if not tokens:
        return True
    content_tokens = [t for t in tokens if t not in _VAGUE_WORDS]
    # If fewer than 2 meaningful words, it's vague
    return len(content_tokens) < 2


def _recall_user_preferences(goal: str) -> str:
    """Pull relevant user preferences and prior context from memory."""
    try:
        from memory.memory_manager import load_memory, search_memory_archive
        memory = load_memory()

        # Pull explicit preferences
        prefs = memory.get("preferences", {})
        pref_lines = []
        for key, entry in list(prefs.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                pref_lines.append(f"- {key.replace('_', ' ').title()}: {val}")

        # Search memory for relevant past knowledge
        results = search_memory_archive(goal, limit=3)
        archive_lines = []
        for item in (results.get("knowledge", []) or [])[:3]:
            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip()
            if title and content:
                archive_lines.append(f"- {title}: {content[:200]}")

        sections = []
        if pref_lines:
            sections.append("User preferences:\n" + "\n".join(pref_lines))
        if archive_lines:
            sections.append("Relevant prior knowledge:\n" + "\n".join(archive_lines))
        return "\n".join(sections)
    except Exception as e:
        print(f"[Planner] ⚠️ Memory recall failed: {e}")
        return ""


def _reformulate_goal(goal: str, memory_context: str = "") -> str:
    """
    If a goal is vague or generic, reformulate it into something specific
    and actionable using a lightweight Gemini call + memory context.
    Returns the original goal unchanged if it's already specific enough.
    """
    if not _goal_is_vague(goal):
        return goal

    try:
        import google.generativeai as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash-lite")

        prompt = f"""You are a query reformulator for an AI assistant.
The user gave a VAGUE or GENERIC request. Your job is to make it SPECIFIC and ACTIONABLE.

Rules:
- Turn generic phrases into specific, searchable queries
- Use the user's known preferences to personalize the query
- Keep the reformulated goal concise (1-2 sentences max)
- Return ONLY the reformulated goal, nothing else
- If the intent is clear despite vague wording, preserve and sharpen it
- Do NOT add instructions to the AI, just rewrite the user's goal

Examples:
- "play something nice" → "play a beautiful ambient lo-fi music video"
- "search for that thing" → (need context) → keep as-is
- "find me a cool video" → "find a highly-rated cinematic short documentary"
- "play some chill music" → "play a lo-fi chill beats study playlist on YouTube"

{f"User Context:{chr(10)}{memory_context}" if memory_context else "(No user context available)"}

Original goal: {goal}
Reformulated goal:"""

        response = model.generate_content(prompt)
        reformulated = response.text.strip().strip('"').strip("'").strip()

        if reformulated and len(reformulated) > 3 and reformulated.lower() != goal.lower():
            print(f"[Planner] 🔄 Reformulated: {goal!r} → {reformulated!r}")
            log_event("planner", "goal_reformulated", f"{goal} → {reformulated}")
            return reformulated

    except Exception as e:
        print(f"[Planner] ⚠️ Reformulation failed: {e}")

    return goal


def create_plan(goal: str, context: str = "") -> dict:
    import google.generativeai as genai

    # Phase 1: Recall user preferences and relevant memory
    memory_context = _recall_user_preferences(goal)

    # Phase 1: Reformulate vague goals into specific ones
    enriched_goal = _reformulate_goal(goal, memory_context=memory_context)

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=PLANNER_PROMPT
    )

    user_input = f"Goal: {enriched_goal}"
    if memory_context:
        user_input += f"\n\nUser Memory Context:\n{memory_context[:1200]}"
    if context:
        user_input += f"\n\nExecution Context: {context}"

    try:
        response = model.generate_content(user_input)
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        plan = json.loads(text)

        if "steps" not in plan or not isinstance(plan["steps"], list):
            raise ValueError("Invalid plan structure")

        for step in plan["steps"]:
            if step.get("tool") in ("generated_code",):
                print(f"[Planner] ⚠️ generated_code detected in step {step.get('step')} — replacing with code_helper")
                desc = step.get("description", goal)
                step["tool"] = "code_helper"
                step["parameters"] = {"action": "build", "description": desc[:400], "language": "python"}

        print(f"[Planner] ✅ Draft Plan: {len(plan['steps'])} steps")
        for s in plan["steps"]:
            print(f"  Step {s['step']}: [{s['tool']}] {s['description']}")

        return plan

    except json.JSONDecodeError as e:
        print(f"[Planner] ⚠️ JSON parse failed: {e}")
        return _fallback_plan(goal)
    except Exception as e:
        print(f"[Planner] ⚠️ Planning failed: {e}")
        return _fallback_plan(goal)


def reflect_and_improve(goal: str, plan: dict, context: str = "") -> dict:
    import google.generativeai as genai

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=PLANNER_PROMPT
    )
    
    print(f"[Planner] 🧠 Reflecting on draft plan for: {goal[:50]}...")
    
    prompt = f"""Goal: {goal}
    
Extra Context:
{context or "(none)"}
    
Draft Plan:
{json.dumps(plan, indent=2)}

CRITIQUE AND IMPROVE the draft plan.
- Are there missing critical steps?
- Are the parameters correct and optimized?
- Is it unnecessarily complex?

Return the final improved plan in JSON format ONLY, adhering strictly to the response rules."""

    try:
        response = model.generate_content(prompt)
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        
        improved_plan = json.loads(text)
        
        for step in improved_plan.get("steps", []):
            if step.get("tool") in ("generated_code",):
                step["tool"] = "code_helper"
                step["parameters"] = {
                    "action": "build",
                    "description": step.get("description", goal)[:400],
                    "language": "python",
                }
                
        print(f"[Planner] ✨ Improved Plan: {len(improved_plan['steps'])} steps")
        return improved_plan
        
    except Exception as e:
        print(f"[Planner] ⚠️ Reflection failed (using draft): {e}")
        return plan


def _fallback_plan(goal: str) -> dict:
    print("[Planner] 🔄 Fallback plan")
    return {
        "goal": goal,
        "steps": [
            {
                "step": 1,
                "tool": "web_search",
                "description": f"Search for: {goal}",
                "parameters": {"query": goal},
                "critical": True
            }
        ]
    }


def replan(goal: str, completed_steps: list, failed_step: dict, error: str, context: str = "") -> dict:
    import google.generativeai as genai

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=PLANNER_PROMPT
    )

    completed_summary = "\n".join(
        f"  - Step {s['step']} ({s['tool']}): DONE" for s in completed_steps
    )

    prompt = f"""Goal: {goal}

Extra Context:
{context or "(none)"}

Already completed:
{completed_summary if completed_summary else '  (none)'}

Failed step: [{failed_step.get('tool')}] {failed_step.get('description')}
Error: {error}

Create a REVISED plan for the remaining work only. Do not repeat completed steps."""

    try:
        response = model.generate_content(prompt)
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        plan     = json.loads(text)

        for step in plan.get("steps", []):
            if step.get("tool") == "generated_code":
                step["tool"] = "code_helper"
                step["parameters"] = {
                    "action": "build",
                    "description": step.get("description", goal)[:400],
                    "language": "python",
                }

        print(f"[Planner] 🔄 Revised plan: {len(plan['steps'])} steps")
        return plan
    except Exception as e:
        print(f"[Planner] ⚠️ Replan failed: {e}")
        return _fallback_plan(goal)
