import unittest
from unittest.mock import patch

from actions.gemini_native import gemini_native


class GeminiNativeActionTests(unittest.TestCase):
    def test_search_formats_citations_and_queries(self):
        with patch(
            "actions.gemini_native.gn.google_search",
            return_value={
                "model": "gemini-3-flash-preview",
                "text": "Spain won Euro 2024.",
                "citations": [{"title": "UEFA", "uri": "https://uefa.com"}],
                "search_queries": ["who won euro 2024"],
            },
        ), patch("actions.gemini_native.log_event"):
            report = gemini_native({"action": "search", "query": "who won euro 2024"})

        self.assertIn("Spain won Euro 2024.", report)
        self.assertIn("Sources:", report)
        self.assertIn("Search queries:", report)

    def test_file_search_requires_explicit_upload_confirmation(self):
        report = gemini_native(
            {
                "action": "file_search",
                "prompt": "Summarize these files",
                "files": ["C:\\Users\\moyes\\Axiom\\README.md"],
            }
        )

        self.assertIn("confirm_upload=true", report)

    def test_code_execution_formats_generated_code_and_output(self):
        with patch(
            "actions.gemini_native.gn.code_execution",
            return_value={
                "model": "gemini-3-flash-preview",
                "text": "The answer is 328.",
                "code_blocks": [{"language": "PYTHON", "code": "print(sum(range(1, 26)))"}],
                "execution_results": [{"outcome": "OUTCOME_OK", "output": "325"}],
            },
        ), patch("actions.gemini_native.log_event"):
            report = gemini_native({"action": "code_execution", "prompt": "Add numbers."})

        self.assertIn("Generated code (PYTHON):", report)
        self.assertIn("Execution output (OUTCOME_OK):", report)


if __name__ == "__main__":
    unittest.main()
