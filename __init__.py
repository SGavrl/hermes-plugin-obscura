"""Obscura browser plugin for Hermes.

Registers Obscura as a browser provider. ``create_session`` either spawns
``obscura serve`` on a free port or connects to ``OBSCURA_CDP_URL`` and hands
Hermes its CDP endpoint. Opt in via ``browser.cloud_provider: obscura`` in
config.yaml; the registry never auto-selects it.

``provider.py`` holds the provider class; ``register`` instantiates and
registers it through the plugin context, the same entry point every Hermes
plugin uses.
"""

from __future__ import annotations

# Hermes may load this plugin as a package (relative import works) or by file
# path (no parent package, so fall back to the sibling module).
try:
    from .provider import ObscuraBrowserProvider
except ImportError:  # pragma: no cover - path-load fallback
    from provider import ObscuraBrowserProvider


def register(ctx) -> None:
    """Called by the Hermes plugin system on load."""
    ctx.register_browser_provider(ObscuraBrowserProvider())
