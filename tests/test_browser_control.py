import asyncio
import unittest
from unittest.mock import patch

from actions import browser_control as bc


class _FakePage:
    def __init__(self):
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


class _FakeContext:
    def __init__(self):
        self.closed = False
        self.pages = []

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self):
        self.closed = False

    def is_connected(self) -> bool:
        return not self.closed

    async def close(self) -> None:
        self.closed = True


class _FakePlaywright:
    def __init__(self):
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class BrowserControlTests(unittest.TestCase):
    def test_close_action_keeps_playwright_runtime_alive(self):
        browser = bc._BrowserThread()
        playwright = _FakePlaywright()

        browser._page = _FakePage()
        browser._context = _FakeContext()
        browser._browser = _FakeBrowser()
        browser._playwright = playwright

        result = asyncio.run(browser._close_browser())

        self.assertEqual(result, "Browser closed.")
        self.assertIsNone(browser._page)
        self.assertIsNone(browser._context)
        self.assertIsNone(browser._browser)
        self.assertIs(browser._playwright, playwright)
        self.assertFalse(playwright.stopped)

    def test_full_shutdown_stops_playwright_runtime(self):
        browser = bc._BrowserThread()
        playwright = _FakePlaywright()

        browser._page = _FakePage()
        browser._context = _FakeContext()
        browser._browser = _FakeBrowser()
        browser._playwright = playwright

        asyncio.run(browser._close())

        self.assertIsNone(browser._page)
        self.assertIsNone(browser._context)
        self.assertIsNone(browser._browser)
        self.assertIsNone(browser._playwright)
        self.assertTrue(playwright.stopped)

    def test_browser_control_returns_clean_error_when_start_fails(self):
        with patch.object(bc, "_ensure_started", side_effect=RuntimeError("boom")):
            result = bc.browser_control({"action": "current_state"})

        self.assertEqual(result, "Browser error: boom")


if __name__ == "__main__":
    unittest.main()
