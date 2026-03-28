# actions/vision_engine.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AXIOM Vision Engine — Real structured perception (not guessing)
#
# Provides:
#   analyze_screen()      → Structured JSON analysis of what's on screen
#   read_text_on_screen() → OCR-grade text extraction
#   find_element()        → Locate UI elements by description
#   detect_errors()       → Find error messages, exceptions, warnings
#   compare_screenshots() → Detect changes between two captures
#   verify_action()       → Post-action visual verification
#
# Uses Gemini 2.5 Flash multimodal (text response, not audio) for reliable
# structured output.  Falls back to local OCR via pytesseract when available.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import base64
import io
import json
import re
import sys
import time
import traceback
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

import cv2
import mss
import mss.tools

try:
    import PIL.Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

try:
    import pytesseract
    _TESSERACT_OK = True
except ImportError:
    _TESSERACT_OK = False

from core.secret_config import get_gemini_api_key

# ── Constants ────────────────────────────────────────────────────────────────

# High-res capture for actual text readability
IMG_MAX_W = 1920
IMG_MAX_H = 1080
JPEG_QUALITY = 82  # Higher quality for text readability

VISION_MODEL = "gemini-2.5-flash"


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class ScreenRegion:
    """Represents a region of the screen."""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    label: str = ""


@dataclass
class VisionResult:
    """Structured result from vision analysis."""
    success: bool = False
    description: str = ""
    text_content: str = ""
    errors_found: list = field(default_factory=list)
    ui_elements: list = field(default_factory=list)
    confidence: float = 0.0
    raw_response: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Image Capture ────────────────────────────────────────────────────────────

def _capture_screenshot(
    monitor_index: int = 1,
    region: Optional[ScreenRegion] = None,
) -> bytes:
    """Capture screen at high resolution. Optionally capture a specific region."""
    with mss.mss() as sct:
        if region:
            mon = {
                "left": region.x,
                "top": region.y,
                "width": region.width,
                "height": region.height,
            }
        else:
            mon = sct.monitors[min(monitor_index, len(sct.monitors) - 1)]

        shot = sct.grab(mon)
        png_bytes = mss.tools.to_png(shot.rgb, shot.size)

    if _PIL_OK:
        img = PIL.Image.open(io.BytesIO(png_bytes)).convert("RGB")
        # Only downscale if larger than our max
        if img.width > IMG_MAX_W or img.height > IMG_MAX_H:
            img.thumbnail((IMG_MAX_W, IMG_MAX_H), PIL.Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return buf.getvalue()
    return png_bytes


def _capture_camera(camera_index: int = 0) -> bytes:
    """Capture from webcam at high quality."""
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Camera {camera_index} could not be opened")

    # Set high resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    # Warm up
    for _ in range(8):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError("Could not capture camera frame")

    if _PIL_OK:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(rgb)
        if img.width > IMG_MAX_W or img.height > IMG_MAX_H:
            img.thumbnail((IMG_MAX_W, IMG_MAX_H), PIL.Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return buf.getvalue()

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return buf.tobytes()


def _image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


# ── Local OCR (Tesseract fallback) ───────────────────────────────────────────

def _local_ocr(image_bytes: bytes) -> str:
    """Extract text using local Tesseract OCR if available."""
    if not _TESSERACT_OK or not _PIL_OK:
        return ""
    try:
        img = PIL.Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(img)
        return text.strip()
    except Exception as e:
        print(f"[Vision] ⚠️ Local OCR failed: {e}")
        return ""


# ── Gemini Vision API ────────────────────────────────────────────────────────

def _gemini_vision_call(image_bytes: bytes, prompt: str, json_mode: bool = False) -> str:
    """Send image + prompt to Gemini Vision and get text response."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=get_gemini_api_key())

    contents = [
        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
        prompt,
    ]

    config = {}
    if json_mode:
        config["response_mime_type"] = "application/json"

    response = client.models.generate_content(
        model=VISION_MODEL,
        contents=contents,
        config=config if config else None,
    )

    return response.text.strip()


# ── Public API ───────────────────────────────────────────────────────────────

def analyze_screen(
    question: str = "What do you see on the screen?",
    source: str = "screen",
    region: Optional[ScreenRegion] = None,
    camera_index: int = 0,
) -> VisionResult:
    """
    Full structured analysis of what's on screen.

    Args:
        question: What to analyze/look for
        source: 'screen' or 'camera'
        region: Optional specific screen region to capture
        camera_index: Which camera to use (if source='camera')

    Returns:
        VisionResult with structured analysis
    """
    result = VisionResult()

    try:
        # Capture
        if source == "camera":
            image_bytes = _capture_camera(camera_index)
        else:
            image_bytes = _capture_screenshot(region=region)

        print(f"[Vision] 📸 Captured {len(image_bytes)} bytes ({source})")

        # Local OCR pass (fast, gives us raw text)
        ocr_text = _local_ocr(image_bytes)
        if ocr_text:
            result.text_content = ocr_text
            print(f"[Vision] 📝 OCR extracted {len(ocr_text)} chars")

        # Gemini Vision pass (deep understanding)
        prompt = f"""You are AXIOM's vision system. Analyze this screenshot with precision.

User's question: {question}

Provide a thorough analysis including:
1. **Description**: What is shown on screen (application, window, content)
2. **Text Content**: Any readable text, code, error messages (quote exactly)
3. **Errors/Problems**: Any error messages, warnings, exceptions visible
4. **UI State**: What state the UI is in (loading, idle, error, success)
5. **Actionable Items**: What can be clicked, typed, or interacted with

{f"OCR pre-scan found this text: {ocr_text[:500]}" if ocr_text else ""}

Be specific and precise. Quote exact text. Don't guess — if you can't read something, say so."""

        raw = _gemini_vision_call(image_bytes, prompt)
        result.raw_response = raw
        result.description = raw
        result.success = True
        result.confidence = 0.85

        # Extract errors if mentioned
        error_patterns = [
            r"(?:error|exception|traceback|failed|fatal)[:.\s].*",
            r"(?:TypeError|ValueError|ImportError|SyntaxError|NameError).*",
        ]
        for pattern in error_patterns:
            matches = re.findall(pattern, raw, re.IGNORECASE)
            result.errors_found.extend(matches[:5])

        print(f"[Vision] ✅ Analysis complete ({len(raw)} chars)")

    except Exception as e:
        result.success = False
        result.description = f"Vision analysis failed: {e}"
        print(f"[Vision] ❌ {e}")
        traceback.print_exc()

    return result


def read_text_on_screen(
    region: Optional[ScreenRegion] = None,
) -> str:
    """
    Extract ALL readable text from the screen.
    Uses Gemini Vision for maximum accuracy (better than OCR alone).
    """
    try:
        image_bytes = _capture_screenshot(region=region)

        prompt = """Extract ALL text visible on this screen, exactly as written.
Include:
- Window titles
- Menu items
- Button labels
- Code/terminal content
- Error messages
- Status bar text
- Any other readable text

Format: Return the raw text with line breaks preserved. Quote EXACTLY what you see.
Do NOT paraphrase or interpret — only extract literal text."""

        return _gemini_vision_call(image_bytes, prompt)

    except Exception as e:
        # Fallback to local OCR
        if _TESSERACT_OK:
            try:
                image_bytes = _capture_screenshot(region=region)
                return _local_ocr(image_bytes) or f"Text extraction failed: {e}"
            except Exception:
                pass
        return f"Text extraction failed: {e}"


def find_element(
    description: str,
    source: str = "screen",
) -> dict:
    """
    Find a UI element on screen by description.
    Returns approximate location and state.
    """
    try:
        image_bytes = _capture_screenshot() if source == "screen" else _capture_camera()

        prompt = f"""Find the UI element described as: "{description}"

Return a JSON object with:
{{
    "found": true/false,
    "element_type": "button/input/link/text/image/icon/menu/tab/other",
    "label": "exact text on the element",
    "approximate_location": "top-left/top-center/top-right/center-left/center/center-right/bottom-left/bottom-center/bottom-right",
    "state": "enabled/disabled/active/selected/hidden",
    "description": "brief description of the element and its context"
}}

Be precise. If multiple matches exist, describe the most prominent one."""

        raw = _gemini_vision_call(image_bytes, prompt, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"found": False, "error": "Could not parse response", "raw": raw[:300]}

    except Exception as e:
        return {"found": False, "error": str(e)}


def detect_errors(source: str = "screen") -> list[dict]:
    """
    Scan screen for any error messages, exceptions, warnings, or failure states.
    Returns a list of detected issues.
    """
    try:
        image_bytes = _capture_screenshot() if source == "screen" else _capture_camera()

        prompt = """Scan this screen for ANY errors, warnings, exceptions, or failure states.

Return a JSON array where each item has:
{{
    "type": "error/warning/exception/failure",
    "severity": "critical/high/medium/low",
    "message": "exact error text quoted from screen",
    "location": "where on screen this appears",
    "likely_cause": "brief explanation",
    "suggested_fix": "what to do about it"
}}

If NO errors are found, return an empty array [].
Be thorough — check terminal output, browser console, dialog boxes, status bars."""

        raw = _gemini_vision_call(image_bytes, prompt, json_mode=True)
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []

    except Exception as e:
        return [{"type": "error", "severity": "high", "message": f"Vision scan failed: {e}"}]


def verify_action(
    expected_outcome: str,
    timeout: float = 2.0,
) -> dict:
    """
    Post-action visual verification.
    Takes a screenshot and checks if the expected outcome is visible.

    Args:
        expected_outcome: What should be visible after the action
        timeout: Wait this many seconds before capturing

    Returns:
        {"verified": bool, "confidence": float, "details": str}
    """
    if timeout > 0:
        time.sleep(timeout)

    try:
        image_bytes = _capture_screenshot()

        prompt = f"""I just performed an action. Verify if the expected outcome is visible.

Expected outcome: "{expected_outcome}"

Analyze the screen and return a JSON object:
{{
    "verified": true/false,
    "confidence": 0.0 to 1.0,
    "what_i_see": "description of what's actually on screen",
    "matches_expected": "how well it matches the expected outcome",
    "issues": "any problems or discrepancies noticed"
}}"""

        raw = _gemini_vision_call(image_bytes, prompt, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"verified": False, "confidence": 0.0, "details": raw[:300]}

    except Exception as e:
        return {"verified": False, "confidence": 0.0, "details": f"Verification failed: {e}"}


def compare_screenshots(
    before_bytes: bytes,
    after_bytes: bytes,
    context: str = "",
) -> dict:
    """Compare two screenshots and describe what changed."""
    from google import genai
    from google.genai import types

    try:
        client = genai.Client(api_key=get_gemini_api_key())

        contents = [
            types.Part.from_bytes(data=before_bytes, mime_type="image/jpeg"),
            "This is the BEFORE screenshot.",
            types.Part.from_bytes(data=after_bytes, mime_type="image/jpeg"),
            f"This is the AFTER screenshot. {f'Context: {context}' if context else ''}\n\n"
            "Compare these two screenshots and describe what changed. Return JSON:\n"
            '{"changes_detected": true/false, "changes": ["list of specific changes"], '
            '"summary": "brief summary of what happened"}',
        ]

        response = client.models.generate_content(
            model=VISION_MODEL,
            contents=contents,
            config={"response_mime_type": "application/json"},
        )

        try:
            return json.loads(response.text.strip())
        except json.JSONDecodeError:
            return {"changes_detected": False, "summary": response.text.strip()[:300]}

    except Exception as e:
        return {"changes_detected": False, "error": str(e)}


# ── Tool interface (called from executor) ────────────────────────────────────

def vision_tool(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """
    Unified vision entry point for the executor tool dispatch.

    parameters:
        action: analyze | read_text | find_element | detect_errors | verify
        question/text: What to look for
        source: screen | camera
        expected: Expected outcome (for verify action)
    """
    p = parameters or {}
    action = str(p.get("action", "analyze")).lower().strip()
    question = str(p.get("question", "") or p.get("text", "") or "What do you see?").strip()
    source = str(p.get("source", "screen")).lower().strip()
    expected = str(p.get("expected", "")).strip()

    if action == "read_text":
        text = read_text_on_screen()
        if speak:
            speak(f"I can see the following text on screen: {text[:200]}")
        return text

    elif action == "find_element":
        result = find_element(question, source)
        summary = json.dumps(result, indent=2)
        if speak:
            if result.get("found"):
                speak(f"Found it — {result.get('label', 'element')} is at {result.get('approximate_location', 'unknown location')}")
            else:
                speak("I couldn't find that element on screen.")
        return summary

    elif action == "detect_errors":
        errors = detect_errors(source)
        if not errors:
            msg = "No errors detected on screen."
            if speak:
                speak(msg)
            return msg
        summary = json.dumps(errors, indent=2)
        if speak:
            speak(f"I found {len(errors)} issue{'s' if len(errors) > 1 else ''} on screen.")
        return summary

    elif action == "verify":
        if not expected:
            return "Please specify what outcome to verify."
        result = verify_action(expected)
        summary = json.dumps(result, indent=2)
        if speak:
            if result.get("verified"):
                speak("Confirmed — the action was successful.")
            else:
                speak("The expected outcome is not visible on screen.")
        return summary

    else:  # analyze (default)
        result = analyze_screen(question=question, source=source)
        if speak:
            speak(result.description[:300] if result.success else "Vision analysis failed.")
        return result.description if result.success else f"Vision failed: {result.description}"
