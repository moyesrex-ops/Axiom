import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import gemini_compat as gc


class GeminiCompatTests(unittest.TestCase):
    def tearDown(self):
        gc.configure(api_key="")

    @patch.object(gc.gn, "_flatten_text", return_value="compat output")
    @patch.object(gc.gn, "generate_response", return_value=SimpleNamespace(text="raw"))
    def test_generate_model_routes_through_shared_runtime(self, response_mock, _flatten_mock):
        gc.configure(api_key="secret-key")
        model = gc.GenerativeModel("gemini-3-flash-preview", system_instruction="Be precise.")

        response = model.generate_content("Hello")

        self.assertEqual(response.text, "compat output")
        response_mock.assert_called_once()
        self.assertEqual(response_mock.call_args.kwargs["model"], "gemini-3-flash-preview")
        self.assertEqual(response_mock.call_args.kwargs["system_instruction"], "Be precise.")
        self.assertEqual(response_mock.call_args.kwargs["api_key"], "secret-key")


if __name__ == "__main__":
    unittest.main()
