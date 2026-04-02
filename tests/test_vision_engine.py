import unittest
from unittest.mock import patch

from actions import vision_engine as ve


class VisionEngineTests(unittest.TestCase):
    def test_analyze_screen_falls_back_to_ocr_when_gemini_unavailable(self):
        with patch.object(ve, "_capture_screenshot", return_value=b"fake-bytes"), patch.object(
            ve,
            "_local_ocr",
            return_value="Inbox\nSecurity alert\nCoinbase price alert",
        ), patch.object(
            ve,
            "_gemini_vision_call",
            side_effect=RuntimeError("503 UNAVAILABLE"),
        ):
            result = ve.analyze_screen(question="What is on screen?")

        self.assertTrue(result.success)
        self.assertIn("OCR-only fallback", result.description)
        self.assertIn("Security alert", result.description)


if __name__ == "__main__":
    unittest.main()
