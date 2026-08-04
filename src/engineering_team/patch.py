"""Work around a CrewAI bug where HTTPS MCP tool names are sanitized on discovery
and the sanitized name is then sent back to the server, making any server-side tool
whose name contains hyphens (e.g. Context7's `resolve-library-id`) unreachable.

Verified present in crewai 1.14.4 through 1.15.10.

The defect, in `crewai/mcp/tool_resolver.py`:

    schemas[sanitize_tool_name(tool.name)] = {...}   # _discover_mcp_tools; original dropped

and then in `_resolve_external`:

    MCPToolWrapper(tool_name=tool_name, ...)         # sanitized key passed as tool_name

`MCPToolWrapper.__init__` documents that parameter as "Original name of the tool on the
MCP server" and stores it as `_original_tool_name`, which `_run` passes verbatim to
`session.call_tool`. So `resolve-library-id` is requested as `resolve_library_id` and the
server returns "unknown tool". A sibling code path in the same file passes
`original_tool_name=` correctly, so this is an inconsistency rather than a design choice.

Scope of the fix
----------------
Only the leaf that loses the information is replaced. An earlier version of this patch
overrode `_resolve_external` wholesale, which silently discarded the TTL schema cache,
exponential-backoff retry and discovery timeouts that 1.15.x added around it.

Two narrow patches instead:

1. `MCPToolResolver._discover_mcp_tools` — same behaviour, but each schema entry also
   carries the unsanitized server-side name. Dict keys stay sanitized, so `_resolve_external`
   and its `#tool` filtering are untouched.
2. `MCPToolWrapper.__init__` — restores `_original_tool_name` from that entry when present.

Importing this module applies both patches as a side effect. Re-verify on crewai upgrade;
`verify_patch_applies()` reports whether the upstream bug is still present.
"""

from __future__ import annotations

import asyncio
from typing import Any

from crewai.mcp import tool_resolver as _tool_resolver
from crewai.mcp.tool_resolver import MCPToolResolver
from crewai.tools.mcp_tool_wrapper import MCPToolWrapper


# Key used to smuggle the unsanitized name through the schema dict. `MCPToolWrapper` only
# reads "args_schema" and "description" from it, so an extra key is inert.
ORIGINAL_NAME_KEY = "__original_tool_name__"


async def _discover_mcp_tools(
    self: MCPToolResolver, server_url: str
) -> dict[str, dict[str, Any]]:
    """Discover tools from an MCP server, preserving each tool's server-side name."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    from crewai.utilities.string_utils import sanitize_tool_name

    async with streamablehttp_client(server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(
                session.initialize(), timeout=_tool_resolver.MCP_CONNECTION_TIMEOUT
            )

            tools_result = await asyncio.wait_for(
                session.list_tools(),
                timeout=_tool_resolver.MCP_DISCOVERY_TIMEOUT
                - _tool_resolver.MCP_CONNECTION_TIMEOUT,
            )

            schemas: dict[str, dict[str, Any]] = {}
            for tool in tools_result.tools:
                sanitized = sanitize_tool_name(tool.name)

                args_schema = None
                if getattr(tool, "inputSchema", None):
                    args_schema = self._json_schema_to_pydantic(
                        sanitized, tool.inputSchema
                    )

                schemas[sanitized] = {
                    "description": getattr(tool, "description", ""),
                    "args_schema": args_schema,
                    ORIGINAL_NAME_KEY: tool.name,
                }
            return schemas


_upstream_wrapper_init = MCPToolWrapper.__init__


def _patched_wrapper_init(
    self: MCPToolWrapper,
    mcp_server_params: dict[str, Any],
    tool_name: str,
    tool_schema: dict[str, Any],
    server_name: str,
) -> None:
    """Build the wrapper as upstream does, then restore the true server-side name.

    The agent-facing tool name stays sanitized — only the name used for `call_tool`
    is corrected.
    """
    _upstream_wrapper_init(
        self,
        mcp_server_params=mcp_server_params,
        tool_name=tool_name,
        tool_schema=tool_schema,
        server_name=server_name,
    )

    original = tool_schema.get(ORIGINAL_NAME_KEY)
    if original:
        self._original_tool_name = original


def verify_patch_applies() -> tuple[bool, str]:
    """Report whether the upstream bug this module patches is still present.

    Returns (still_needed, explanation). Call after an upgrade: once upstream keys
    discovery by the original name or threads `original_tool_name` through
    `_resolve_external`, this patch becomes dead code and should be deleted.
    """
    import inspect

    try:
        source = inspect.getsource(MCPToolResolver._resolve_external)
    except (OSError, TypeError) as exc:  # pragma: no cover - defensive
        return True, f"could not inspect _resolve_external ({exc}); assuming still needed"

    if "original_tool_name=" in source:
        return False, "_resolve_external now passes original_tool_name; patch is obsolete"
    return True, "_resolve_external still passes the sanitized name as tool_name"


MCPToolResolver._discover_mcp_tools = _discover_mcp_tools  # type: ignore[method-assign]
MCPToolWrapper.__init__ = _patched_wrapper_init  # type: ignore[method-assign]

# Discovery results are cached module-level with a TTL. Anything resolved before this
# import would hold pre-patch schemas, so drop the cache to be safe.
_tool_resolver._mcp_schema_cache.clear()
