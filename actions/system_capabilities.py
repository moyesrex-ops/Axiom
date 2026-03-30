from core.capabilities import collect_capabilities, format_capability_report, format_operator_surface
from core.comms_surface import format_comms_status
from core.system_context import format_system_context
from core.tool_catalog import format_brain_surface, format_tool_catalog
from memory.memory_manager import save_to_nexus
from memory.runtime_store import (
    log_capability,
    log_event,
    recent_events,
    recent_failures,
    recent_task_runs,
)


def _snapshot_capabilities() -> None:
    caps = collect_capabilities()
    for name, value in caps.items():
        log_capability(name, "available" if value else "unavailable", str(value))


def system_capabilities(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "summary")).strip().lower()
    limit = int(params.get("limit", 8) or 8)

    if action in ("summary", "status"):
        _snapshot_capabilities()
        report = format_capability_report()
        log_event("capabilities", "capability_snapshot", report[:2000])
        try:
            save_to_nexus("Capability Snapshot", report[:2000])
        except Exception:
            pass
        return report

    if action == "doctor":
        try:
            from core.doctor import format_doctor_report

            report = format_doctor_report(limit=limit)
            log_event("capabilities", "doctor_report", report[:2000])
            try:
                save_to_nexus("Boot Doctor", report[:2000], kind="capability", source="doctor")
            except Exception:
                pass
            return report
        except Exception as error:
            return f"Doctor report failed: {error}"

    if action == "context":
        report = format_system_context()
        log_event("capabilities", "system_context", report[:2000])
        return report

    if action in ("operator", "routing"):
        report = format_operator_surface(limit=limit)
        log_event("capabilities", "operator_surface", report[:2000])
        return report

    if action == "brain":
        report = f"{format_operator_surface(limit=limit)}\n\n{format_brain_surface(limit=limit)}"
        log_event("capabilities", "brain_surface", report[:2000])
        return report

    if action == "tools":
        report = format_tool_catalog(limit=limit * 4 if limit > 0 else 0)
        log_event("capabilities", "tool_catalog", report[:2000])
        return report

    if action in ("communications", "comms"):
        report = format_comms_status()
        log_event("capabilities", "communications_status", report[:2000])
        return report

    if action == "hardware":
        try:
            from actions.computer_settings import hardware_status

            report = hardware_status()
            log_event("capabilities", "hardware_status", report[:2000])
            return report
        except Exception as error:
            return f"Hardware status failed: {error}"

    if action == "integrations":
        try:
            from core.agent_library import format_agent_library_status
            from core.autoresearch_bridge import format_autoresearch_status
            from core.automaton_bridge import format_automaton_status
            from core.crucix_bridge import format_crucix_status
            from core.deerflow_bridge import format_deerflow_status
            from core.dexter_bridge import format_dexter_status
            from core.lightpanda_bridge import format_lightpanda_status
            from core.lossless_claw_bridge import format_lossless_claw_status
            from core.mirofish_bridge import format_mirofish_status
            from core.openfang_bridge import format_openfang_status
            from core.pentagi_bridge import format_pentagi_status
            from core.paperclip_bridge import format_paperclip_status
            from core.trade_daemon import format_trade_daemon_status
            from core.tradingagents_bridge import format_tradingagents_status
            from core.symphony_bridge import format_symphony_status
            from core.learning_orchestrator import format_learning_status

            report = (
                f"{format_mirofish_status()}\n\n"
                f"{format_automaton_status()}\n\n"
                f"{format_dexter_status()}\n\n"
                f"{format_pentagi_status()}\n\n"
                f"{format_tradingagents_status(limit=limit)}\n\n"
                f"{format_trade_daemon_status()}\n\n"
                f"{format_lightpanda_status()}\n\n"
                f"{format_autoresearch_status(limit=limit)}\n\n"
                f"{format_deerflow_status(limit=limit)}\n\n"
                f"{format_crucix_status()}\n\n"
                f"{format_paperclip_status()}\n\n"
                f"{format_openfang_status()}\n\n"
                f"{format_symphony_status()}\n\n"
                f"{format_lossless_claw_status()}\n\n"
                f"{format_learning_status(limit=limit)}\n\n"
                f"{format_agent_library_status(limit=limit)}"
            )
            log_event("capabilities", "integrations_status", report[:2000])
            return report
        except Exception as error:
            return f"Integration status failed: {error}"

    if action == "mirofish":
        try:
            from core.mirofish_bridge import format_mirofish_status

            report = format_mirofish_status()
            log_event("capabilities", "mirofish_status", report[:2000])
            return report
        except Exception as error:
            return f"MiroFish status failed: {error}"

    if action == "automaton":
        try:
            from core.automaton_bridge import format_automaton_status

            report = format_automaton_status()
            log_event("capabilities", "automaton_status", report[:2000])
            return report
        except Exception as error:
            return f"Automaton status failed: {error}"

    if action == "lightpanda":
        try:
            from core.lightpanda_bridge import format_lightpanda_status

            report = format_lightpanda_status()
            log_event("capabilities", "lightpanda_status", report[:2000])
            return report
        except Exception as error:
            return f"Lightpanda status failed: {error}"

    if action == "autoresearch":
        try:
            from core.autoresearch_bridge import format_autoresearch_status

            report = format_autoresearch_status(limit=limit)
            log_event("capabilities", "autoresearch_status", report[:2000])
            return report
        except Exception as error:
            return f"Autoresearch status failed: {error}"

    if action == "deerflow":
        try:
            from core.deerflow_bridge import format_deerflow_status

            report = format_deerflow_status(limit=limit)
            log_event("capabilities", "deerflow_status", report[:2000])
            return report
        except Exception as error:
            return f"DeerFlow status failed: {error}"

    if action == "crucix":
        try:
            from core.crucix_bridge import format_crucix_status

            report = format_crucix_status()
            log_event("capabilities", "crucix_status", report[:2000])
            return report
        except Exception as error:
            return f"Crucix status failed: {error}"

    if action == "learning":
        try:
            from core.learning_orchestrator import format_learning_status

            report = format_learning_status(limit=limit)
            log_event("capabilities", "learning_status", report[:2000])
            return report
        except Exception as error:
            return f"Learning status failed: {error}"

    if action == "paperclip":
        try:
            from core.paperclip_bridge import format_paperclip_status

            report = format_paperclip_status()
            log_event("capabilities", "paperclip_status", report[:2000])
            return report
        except Exception as error:
            return f"Paperclip status failed: {error}"

    if action == "openfang":
        try:
            from core.openfang_bridge import format_openfang_status

            report = format_openfang_status()
            log_event("capabilities", "openfang_status", report[:2000])
            return report
        except Exception as error:
            return f"OpenFang status failed: {error}"

    if action == "symphony":
        try:
            from core.symphony_bridge import format_symphony_status

            report = format_symphony_status()
            log_event("capabilities", "symphony_status", report[:2000])
            return report
        except Exception as error:
            return f"Symphony status failed: {error}"

    if action == "lossless_claw":
        try:
            from core.lossless_claw_bridge import format_lossless_claw_status

            report = format_lossless_claw_status()
            log_event("capabilities", "lossless_claw_status", report[:2000])
            return report
        except Exception as error:
            return f"lossless-claw status failed: {error}"

    if action == "skills":
        try:
            from core.skill_library import format_skill_library_status

            report = format_skill_library_status(limit=limit)
            log_event("capabilities", "skill_library_status", report[:2000])
            return report
        except Exception as error:
            return f"Skill library status failed: {error}"

    if action == "agents":
        try:
            from core.agent_library import format_agent_library_status

            report = format_agent_library_status(limit=limit)
            log_event("capabilities", "agent_library_status", report[:2000])
            return report
        except Exception as error:
            return f"Agent library status failed: {error}"

    if action == "dexter":
        try:
            from core.dexter_bridge import format_dexter_status

            report = format_dexter_status()
            log_event("capabilities", "dexter_status", report[:2000])
            return report
        except Exception as error:
            return f"Dexter status failed: {error}"

    if action == "pentagi":
        try:
            from core.pentagi_bridge import format_pentagi_status

            report = format_pentagi_status()
            log_event("capabilities", "pentagi_status", report[:2000])
            return report
        except Exception as error:
            return f"PentAGI status failed: {error}"

    if action == "tradingagents":
        try:
            from core.tradingagents_bridge import format_tradingagents_status

            report = format_tradingagents_status(limit=limit)
            log_event("capabilities", "tradingagents_status", report[:2000])
            return report
        except Exception as error:
            return f"TradingAgents status failed: {error}"

    if action in ("trade_daemon", "trading_daemon"):
        try:
            from core.trade_daemon import format_trade_daemon_status

            report = format_trade_daemon_status()
            log_event("capabilities", "trade_daemon_status", report[:2000])
            return report
        except Exception as error:
            return f"Trade daemon status failed: {error}"

    if action == "failures":
        rows = recent_failures(limit=limit)
        if not rows:
            session_rows = recent_events(limit=max(limit * 3, 18), kind="session")
            connection_errors = [row for row in session_rows if row.get("topic") == "connection_error"]
            reconnects = [row for row in session_rows if row.get("topic") == "reconnected"]
            recoveries = [row for row in session_rows if row.get("topic") == "partial_turn_recovered"]
            if connection_errors or reconnects or recoveries:
                return (
                    "No rows exist in the failures table, but session instability was detected.\n"
                    f"- connection_error events: {len(connection_errors)}\n"
                    f"- reconnected events: {len(reconnects)}\n"
                    f"- partial_turn_recovered events: {len(recoveries)}"
                )
            return "No recent failures recorded."
        lines = ["Recent failures"]
        for row in rows:
            lines.append(
                f"- #{row['id']} [{row['tool']}] {row['description'][:80]} | "
                f"resolved={bool(row['resolved'])} | error={row['error'][:120]}"
            )
        return "\n".join(lines)

    if action == "events":
        rows = recent_events(limit=limit)
        if not rows:
            return "No recent runtime events recorded."
        lines = ["Recent runtime events"]
        for row in rows:
            lines.append(
                f"- #{row['id']} [{row['kind']}] {row['topic']}: {row['content'][:120]}"
            )
        return "\n".join(lines)

    if action == "tasks":
        rows = recent_task_runs(limit=limit)
        if not rows:
            return "No recent task checkpoints recorded."
        lines = ["Recent task checkpoints"]
        for row in rows:
            metadata = dict(row.get("metadata") or {})
            phase = str(metadata.get("phase", "") or "").strip().lower()
            channel = str(metadata.get("channel", "") or "").strip().lower()
            suffix = []
            if phase:
                suffix.append(f"phase={phase}")
            if channel:
                suffix.append(f"channel={channel}")
            lines.append(
                f"- [{row['task_id']}] {row['status']} | {row['goal'][:90]} | "
                f"updated={row['updated_at']}"
                + (f" | {' '.join(suffix)}" if suffix else "")
            )
        return "\n".join(lines)

    return (
        "Unknown action. Use summary, status, doctor, context, hardware, integrations, "
        "mirofish, automaton, dexter, pentagi, tradingagents, trade_daemon, lightpanda, autoresearch, deerflow, "
        "paperclip, openfang, symphony, lossless_claw, skills, agents, failures, events, or tasks."
    )
