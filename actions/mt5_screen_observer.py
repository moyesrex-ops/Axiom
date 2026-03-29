from __future__ import annotations

import json
import re

from actions.vision_engine import analyze_screen, read_text_on_screen
from core import gemini_native as gn
from memory.runtime_store import log_event

_TIMEFRAME_PATTERN = re.compile(r"\b(M1|M2|M3|M4|M5|M6|M10|M12|M15|M20|M30|H1|H2|H3|H4|H6|H8|H12|D1|W1|MN1)\b", re.IGNORECASE)
_SYMBOL_PATTERN = re.compile(r"\b([A-Z]{3,6}(?:USD|JPY|CAD|CHF|AUD|NZD|EUR|GBP)|XAUUSD|XAGUSD|BTCUSD|ETHUSD|US30|NAS100|SPX500|GOLD)\b")


def _excerpt(text: str, limit: int = 1000) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 14].rstrip() + " [truncated]"


def _fallback_extract_symbol(text: str, symbol_hint: str = "") -> str:
    hint = str(symbol_hint or "").strip().upper()
    haystack = str(text or "")
    if hint and hint in haystack.upper():
        return hint
    match = _SYMBOL_PATTERN.search(haystack.upper())
    return str(match.group(1) if match else hint)


def _fallback_extract_timeframe(text: str) -> str:
    match = _TIMEFRAME_PATTERN.search(str(text or "").upper())
    return str(match.group(1) if match else "")


def _fallback_snapshot(analysis_text: str, ocr_text: str, symbol_hint: str = "") -> dict:
    combined = "\n".join(part for part in (analysis_text, ocr_text) if str(part or "").strip())
    lowered = combined.lower()
    errors = []
    for token in ("order failed", "retcode", "invalid", "error", "rejected", "not recognized"):
        if token in lowered:
            errors.append(token)
    return {
        "mt5_visible": "metatrader" in lowered or "mt5" in lowered or "meta trader" in lowered,
        "symbol": _fallback_extract_symbol(combined, symbol_hint=symbol_hint),
        "timeframe": _fallback_extract_timeframe(combined),
        "positions_visible": "position" in lowered or "trade" in lowered or "profit" in lowered,
        "open_positions_count": None,
        "floating_pl": "",
        "balance": "",
        "equity": "",
        "chart_bias": "unclear",
        "execution_error": ", ".join(errors),
        "confidence": 0.35,
        "summary": _excerpt(analysis_text or ocr_text, limit=400),
    }


def observe_mt5_screen(symbol_hint: str = "") -> dict:
    question = (
        "Inspect the current screen for MetaTrader 5. Focus on whether MT5 is visible, the active chart symbol, "
        "the visible timeframe, any open positions or trade panel, account/balance/equity or floating P/L if shown, "
        "any alerts or order errors, and the visible chart direction or bias."
    )
    analysis = analyze_screen(question=question, source="screen")
    analysis_text = str(analysis.description or "").strip()
    ocr_text = str(analysis.text_content or "").strip()
    if not ocr_text:
        raw_text = read_text_on_screen()
        ocr_text = raw_text if not raw_text.startswith("Text extraction failed:") else ""

    schema = {
        "type": "OBJECT",
        "properties": {
            "mt5_visible": {"type": "BOOLEAN"},
            "symbol": {"type": "STRING"},
            "timeframe": {"type": "STRING"},
            "positions_visible": {"type": "BOOLEAN"},
            "open_positions_count": {"type": "INTEGER"},
            "floating_pl": {"type": "STRING"},
            "balance": {"type": "STRING"},
            "equity": {"type": "STRING"},
            "chart_bias": {"type": "STRING", "enum": ["bullish", "bearish", "range", "mixed", "unclear"]},
            "execution_error": {"type": "STRING"},
            "confidence": {"type": "NUMBER"},
            "summary": {"type": "STRING"},
        },
        "required": [
            "mt5_visible",
            "symbol",
            "timeframe",
            "positions_visible",
            "chart_bias",
            "execution_error",
            "confidence",
            "summary",
        ],
    }

    prompt = f"""Structure this MetaTrader 5 screen observation.
Return strict JSON only.

Symbol hint: {symbol_hint or "none"}

[VISION ANALYSIS]
{analysis_text or "none"}

[OCR TEXT]
{ocr_text or "none"}

Rules:
- Only report what is actually visible from the current screen context.
- If a field is not visible, leave it empty or use false/null.
- For chart_bias, use bullish, bearish, range, mixed, or unclear.
- execution_error should contain a visible MT5 or order error if one is shown.
"""

    try:
        payload = gn.generate_json(
            prompt,
            model=gn.reflection_model_name(),
            schema=schema,
            system_instruction="You structure visible MetaTrader 5 screen state for AXIOM. Be literal and conservative.",
        )
        snapshot = {
            "mt5_visible": bool(payload.get("mt5_visible", False)),
            "symbol": str(payload.get("symbol", "") or "").strip().upper(),
            "timeframe": str(payload.get("timeframe", "") or "").strip().upper(),
            "positions_visible": bool(payload.get("positions_visible", False)),
            "open_positions_count": payload.get("open_positions_count"),
            "floating_pl": str(payload.get("floating_pl", "") or "").strip(),
            "balance": str(payload.get("balance", "") or "").strip(),
            "equity": str(payload.get("equity", "") or "").strip(),
            "chart_bias": str(payload.get("chart_bias", "unclear") or "unclear").strip().lower(),
            "execution_error": str(payload.get("execution_error", "") or "").strip(),
            "confidence": float(payload.get("confidence", 0.0) or 0.0),
            "summary": str(payload.get("summary", "") or "").strip(),
        }
    except Exception:
        snapshot = _fallback_snapshot(analysis_text, ocr_text, symbol_hint=symbol_hint)

    if not snapshot.get("symbol"):
        snapshot["symbol"] = _fallback_extract_symbol("\n".join([analysis_text, ocr_text]), symbol_hint=symbol_hint)
    if not snapshot.get("timeframe"):
        snapshot["timeframe"] = _fallback_extract_timeframe("\n".join([analysis_text, ocr_text]))

    snapshot["analysis_excerpt"] = _excerpt(analysis_text)
    snapshot["ocr_excerpt"] = _excerpt(ocr_text)
    return snapshot


def format_mt5_screen_state(snapshot: dict) -> str:
    payload = dict(snapshot or {})
    lines = [
        "MT5 screen state",
        f"Visible: {'yes' if payload.get('mt5_visible') else 'no'}",
        f"Symbol: {payload.get('symbol') or 'not detected'}",
        f"Timeframe: {payload.get('timeframe') or 'not detected'}",
        f"Positions panel visible: {'yes' if payload.get('positions_visible') else 'no'}",
        f"Chart bias: {payload.get('chart_bias') or 'unclear'}",
        f"Confidence: {float(payload.get('confidence', 0.0) or 0.0):.2f}",
    ]
    if payload.get("open_positions_count") not in (None, ""):
        lines.append(f"Open positions visible: {payload['open_positions_count']}")
    if payload.get("floating_pl"):
        lines.append(f"Floating P/L: {payload['floating_pl']}")
    if payload.get("balance"):
        lines.append(f"Balance: {payload['balance']}")
    if payload.get("equity"):
        lines.append(f"Equity: {payload['equity']}")
    if payload.get("execution_error"):
        lines.append(f"Visible execution error: {payload['execution_error']}")
    if payload.get("summary"):
        lines.append(f"Summary: {payload['summary'][:400]}")
    return "\n".join(lines)


def log_mt5_screen_state(snapshot: dict, *, topic: str, symbol_hint: str = "") -> None:
    report = format_mt5_screen_state(snapshot)
    log_event(
        "trading",
        topic,
        report[:2000],
        metadata={
            "symbol_hint": symbol_hint,
            "visible": bool(snapshot.get("mt5_visible", False)),
            "symbol": str(snapshot.get("symbol", "") or ""),
            "timeframe": str(snapshot.get("timeframe", "") or ""),
            "chart_bias": str(snapshot.get("chart_bias", "") or ""),
        },
    )
