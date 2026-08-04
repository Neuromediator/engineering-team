"""Regression tests for the MCP tool-name patch.

Uses stdlib `unittest` only — the project ships no test framework, and the crew itself
is instructed to write stdlib tests, so the harness follows the same rule.

Run with:
    uv run python -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engineering_team import patch  # noqa: E402
from crewai.mcp.tool_resolver import MCPToolResolver  # noqa: E402
from crewai.tools.mcp_tool_wrapper import MCPToolWrapper  # noqa: E402


class _FakeSession:
    """Stands in for `mcp.ClientSession`."""

    def __init__(self, tools):
        self._tools = tools

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def initialize(self):
        return None

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)


class _FakeTransport:
    async def __aenter__(self):
        return (None, None, None)

    async def __aexit__(self, *exc):
        return False


class WrapperOriginalNameTest(unittest.TestCase):
    """`MCPToolWrapper` must call the server using its true, unsanitized tool name."""

    def _build(self, schema):
        return MCPToolWrapper(
            mcp_server_params={"url": "https://example.test/mcp"},
            tool_name="resolve_library_id",
            tool_schema=schema,
            server_name="ctx7",
        )

    def test_restores_hyphenated_server_side_name(self):
        wrapper = self._build(
            {
                "description": "Resolve a library id",
                "args_schema": None,
                patch.ORIGINAL_NAME_KEY: "resolve-library-id",
            }
        )
        self.assertEqual(wrapper.original_tool_name, "resolve-library-id")

    def test_agent_facing_name_stays_sanitized(self):
        """Hyphens must not leak into the name exposed to the LLM."""
        wrapper = self._build(
            {"description": "d", "args_schema": None, patch.ORIGINAL_NAME_KEY: "resolve-library-id"}
        )
        self.assertNotIn("-", wrapper.name)
        self.assertEqual(wrapper.name, "ctx7_resolve_library_id")

    def test_upstream_behaviour_preserved_without_key(self):
        """Absent the smuggled key the wrapper must behave exactly as upstream does."""
        wrapper = self._build({"description": "d", "args_schema": None})
        self.assertEqual(wrapper.original_tool_name, "resolve_library_id")


class DiscoveryPreservesOriginalNameTest(unittest.TestCase):
    """`_discover_mcp_tools` keys by sanitized name but must retain the original."""

    def _discover(self, tools):
        resolver = MCPToolResolver(agent=None, logger=mock.MagicMock())
        with (
            mock.patch("mcp.ClientSession", lambda *a, **k: _FakeSession(tools)),
            mock.patch(
                "mcp.client.streamable_http.streamablehttp_client",
                lambda *a, **k: _FakeTransport(),
            ),
        ):
            return asyncio.run(resolver._discover_mcp_tools("https://example.test/mcp"))

    def test_keys_sanitized_values_carry_original(self):
        schemas = self._discover(
            [
                SimpleNamespace(name="resolve-library-id", description="a", inputSchema=None),
                SimpleNamespace(name="query-docs", description="b", inputSchema=None),
            ]
        )

        self.assertEqual(set(schemas), {"resolve_library_id", "query_docs"})
        self.assertEqual(
            schemas["resolve_library_id"][patch.ORIGINAL_NAME_KEY], "resolve-library-id"
        )
        self.assertEqual(schemas["query_docs"][patch.ORIGINAL_NAME_KEY], "query-docs")

    def test_description_still_populated(self):
        schemas = self._discover(
            [SimpleNamespace(name="query-docs", description="Search docs", inputSchema=None)]
        )
        self.assertEqual(schemas["query_docs"]["description"], "Search docs")

    def test_names_without_hyphens_unaffected(self):
        schemas = self._discover(
            [SimpleNamespace(name="search", description="", inputSchema=None)]
        )
        self.assertEqual(schemas["search"][patch.ORIGINAL_NAME_KEY], "search")


class UpstreamDriftTest(unittest.TestCase):
    def test_patch_is_still_required(self):
        """Fails once upstream fixes the bug — the signal to delete patch.py entirely.

        Deliberately noisy: a silently-unnecessary monkey-patch is worse than none.
        """
        still_needed, explanation = patch.verify_patch_applies()
        self.assertTrue(
            still_needed,
            f"crewai appears to have fixed this upstream ({explanation}). "
            "Delete src/engineering_team/patch.py, its import in main.py, and this test.",
        )


if __name__ == "__main__":
    unittest.main()
