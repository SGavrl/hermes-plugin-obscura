"""Obscura local browser plugin for Hermes.

Registers Obscura as a browser provider: instead of calling a cloud API,
``create_session`` spawns ``obscura serve`` on a free port and hands the agent
its CDP endpoint. Opt-in via ``browser.cloud_provider: obscura`` in config.yaml;
the registry never auto-selects it.

``provider.py`` holds the provider class; ``register`` instantiates and
registers it through the plugin context, the same entry point every Hermes
plugin uses.
"""

from __future__ import annotations

import json
import os

# Hermes may load this plugin as a package (relative import works) or by file
# path (no parent package, so fall back to the sibling module).
try:
    from .provider import ObscuraBrowserProvider, _bearer_headers, _mcp_url, _remote_cdp_base
except ImportError:  # pragma: no cover - path-load fallback
    from provider import ObscuraBrowserProvider, _bearer_headers, _mcp_url, _remote_cdp_base


def _obscura_browser_info_impl(_: dict) -> str:
    """Return the live Obscura CDP/MCP endpoints + auth metadata as JSON.

    The agent uses this to discover whether the Obscura backend exposes a
    CDP endpoint (browser-native mode) and/or a MCP endpoint (server-style
    tool mode). Returning the bearer presence (without the secret value)
    lets the agent pick the right path without leaking credentials.
    """
    cdp_base = _remote_cdp_base()
    mcp = _mcp_url()
    payload = {
        "provider": "obscura",
        "cdp_base": cdp_base,
        "mcp_url": mcp,
        "auth": "bearer" if os.environ.get("OBSCURA_BEARER_TOKEN", "").strip() else "none",
    }
    return json.dumps(payload, indent=2)


def register(ctx) -> None:
    """Called by the Hermes plugin system on load."""
    ctx.register_browser_provider(ObscuraBrowserProvider())
    ctx.register_tool(
        name="obscura_browser_info",
        toolset="browser-obscura",
        schema={
            "name": "obscura_browser_info",
            "description": (
                "Return the active Obscura CDP/MCP endpoints and auth mode "
                "(bearer|none) so the caller can decide whether to use the "
                "native browser via CDP or the server-style tool via MCP."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
        handler=_obscura_browser_info_impl,
        description="Describe Obscura browser backend endpoints.",
        emoji="🕵️",
    )
