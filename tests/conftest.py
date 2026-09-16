"""Test setup for the standalone plugin repo.

`provider.py` imports `agent.browser_provider.BrowserProvider` and
`hermes_constants.get_hermes_home` from Hermes core. When the tests run inside
a full Hermes checkout those imports resolve normally. When they run standalone
(this repo's own CI, where Hermes is not installed), we register minimal stubs
so the provider imports and its lifecycle can be exercised against the real
`obscura serve` spawn path. The stubs mirror only the imported surface.
"""

from __future__ import annotations

import abc
import importlib.util
import os
import sys
import types
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _install_browser_provider_stub() -> None:
    try:
        if importlib.util.find_spec("agent.browser_provider") is not None:
            return  # Real Hermes is available; use it.
    except ModuleNotFoundError:
        pass  # `agent` package absent (standalone run); fall through to the stub.

    agent_pkg = sys.modules.get("agent")
    if agent_pkg is None:
        agent_pkg = types.ModuleType("agent")
        agent_pkg.__path__ = []  # mark as a package
        sys.modules["agent"] = agent_pkg

    mod = types.ModuleType("agent.browser_provider")

    class BrowserProvider(abc.ABC):
        @property
        @abc.abstractmethod
        def name(self) -> str: ...

        @property
        def display_name(self) -> str:
            return self.name

        @abc.abstractmethod
        def is_available(self) -> bool: ...

        @abc.abstractmethod
        def create_session(self, task_id: str) -> Dict[str, object]: ...

        @abc.abstractmethod
        def close_session(self, session_id: str) -> bool: ...

        @abc.abstractmethod
        def emergency_cleanup(self, session_id: str) -> None: ...

        def get_setup_schema(self) -> Dict[str, Any]:
            return {}

        def is_configured(self) -> bool:
            return True

    mod.BrowserProvider = BrowserProvider
    sys.modules["agent.browser_provider"] = mod
    setattr(agent_pkg, "browser_provider", mod)


def _install_hermes_constants_stub() -> None:
    if importlib.util.find_spec("hermes_constants") is not None:
        return  # Real Hermes is available; use its resolver.

    mod = types.ModuleType("hermes_constants")

    def get_hermes_home() -> Path:
        configured = os.environ.get("HERMES_HOME", "").strip()
        return Path(configured) if configured else Path.home() / ".hermes"

    mod.get_hermes_home = get_hermes_home
    sys.modules["hermes_constants"] = mod


def _load_provider_module() -> None:
    """Import provider.py by file path as the top-level module ``provider`` so
    ``from provider import ObscuraBrowserProvider`` in the tests resolves without
    importing the repo-root package ``__init__`` (whose relative import only
    works when Hermes loads the plugin as a package)."""
    if "provider" in sys.modules:
        return
    spec = importlib.util.spec_from_file_location("provider", _REPO_ROOT / "provider.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["provider"] = module
    spec.loader.exec_module(module)


_install_browser_provider_stub()
_install_hermes_constants_stub()
_load_provider_module()
