from __future__ import annotations

from dataclasses import dataclass

from core import gemini_native as gn

_CONFIGURED_API_KEY = ""


def configure(*, api_key: str = "", **_: object) -> None:
    global _CONFIGURED_API_KEY
    _CONFIGURED_API_KEY = str(api_key or "").strip()


@dataclass
class _CompatResponse:
    text: str


class GenerativeModel:
    def __init__(self, model_name: str = "", system_instruction: str = "", **_: object) -> None:
        self.model_name = str(model_name or "").strip() or gn.reflection_model_name()
        self.system_instruction = str(system_instruction or "").strip()

    def generate_content(self, contents):
        response = gn.generate_response(
            contents,
            model=self.model_name,
            system_instruction=self.system_instruction,
            api_key=_CONFIGURED_API_KEY,
        )
        return _CompatResponse(text=gn._flatten_text(response))
