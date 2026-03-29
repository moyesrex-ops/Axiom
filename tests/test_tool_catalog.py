import unittest

from core.tool_catalog import canonical_tool_name, tool_alias_count, tool_catalog_rows


class ToolCatalogTests(unittest.TestCase):
    def test_aliases_resolve_to_canonical_tools(self):
        self.assertEqual(canonical_tool_name("communications"), "comms_control")
        self.assertEqual(canonical_tool_name("screen_processor"), "vision_tool")
        self.assertEqual(canonical_tool_name("mt5"), "mt5_trading")

    def test_catalog_exposes_aliases(self):
        rows = tool_catalog_rows(category="communications")
        names = {row["name"] for row in rows}
        self.assertIn("comms_control", names)
        self.assertGreater(tool_alias_count(), 0)


if __name__ == "__main__":
    unittest.main()
