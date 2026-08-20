"""Obscura local browser provider, plugin form.

Subclasses :class:`agent.browser_provider.BrowserProvider`. Unlike the cloud
backends (Browserbase, Browser Use, Firecrawl) this provider runs a *local*
browser: it spawns ``obscura serve`` as a subprocess and hands the agent the
process's CDP endpoint. Obscura (https://github.com/h4ckf0r0day/obscura) is a
Rust headless browser that speaks the Chrome DevTools Protocol with no Chrome
or Node.js dependency, a single ~70 MB binary.

Opt-in only. The registry never auto-selects Obscura; choose it explicitly::

    browser:
      cloud_provider: "obscura"

Two modes:

- **Local (default)** spawns ``obscura serve`` as a subprocess and owns its
  lifecycle.
- **Remote** connects to an already-running ``obscura serve`` (for example one
  running in Docker or on another host). Set ``OBSCURA_CDP_URL`` and the provider
  connects instead of spawning; the external server owns its own lifecycle, so
  the provider never starts or stops it. This is how you run Obscura in its own
  container: ``docker run -p 9222:9222 <obscura-image> serve --host 0.0.0.0``
  then ``OBSCURA_CDP_URL=http://127.0.0.1:9222``.

Env vars::

    OBSCURA_CDP_URL=             # connect to a running server (remote mode); unset = spawn locally
    OBSCURA_BIN=obscura          # local mode: binary path, or a name on PATH (default "obscura")
    OBSCURA_STEALTH=false        # local mode: pass --stealth (default false)
    OBSCURA_PORT=                # local mode: fixed CDP port (default: an ephemeral free port)
    OBSCURA_STARTUP_TIMEOUT=15   # seconds to wait for the CDP server (default 15)
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
from typing import Any, Dict, Optional

import requests

from agent.browser_provider import BrowserProvider

logger = logging.getLogger(__name__)

_DEFAULT_BIN = "obscura"
_DEFAULT_STARTUP_TIMEOUT = 15.0


class ObscuraBrowserProvider(BrowserProvider):
    """Local Obscura (https://github.com/h4ckf0r0day/obscura) CDP browser.

    Spawns one ``obscura serve`` process per session and tears it down on
    close. Lives entirely on localhost; no credentials or network calls.
    """

    def __init__(self) -> None:
        # bb_session_id -> the obscura serve process that session owns (local mode).
        self._procs: Dict[str, subprocess.Popen] = {}
        # Session ids served by an external server (remote mode): nothing to
        # tear down, but we track them so close_session can tell a known remote
        # session from a genuinely unknown id.
        self._remote_sessions: set = set()
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "obscura"

    @property
    def display_name(self) -> str:
        return "Obscura"

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def _resolve_binary(self) -> Optional[str]:
        """Resolve the obscura executable, or None if it cannot be found.

        ``shutil.which`` handles a path (absolute or relative) and a bare name
        on PATH alike, and appends the Windows executable suffix. Cheap and
        offline: it never spawns anything.
        """
        return shutil.which(os.environ.get("OBSCURA_BIN", _DEFAULT_BIN))

    def is_available(self) -> bool:
        # Remote mode needs no local binary, just a reachable server URL.
        if _remote_cdp_base() is not None:
            return True
        return self._resolve_binary() is not None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, task_id: str) -> Dict[str, object]:
        remote_base = _remote_cdp_base()
        if remote_base is not None:
            return self._create_remote_session(task_id, remote_base)

        binary = self._resolve_binary()
        if binary is None:
            raise ValueError(
                "Obscura binary not found. Install obscura "
                "(https://github.com/h4ckf0r0day/obscura), put it on PATH, or set "
                "OBSCURA_BIN to its path."
            )

        stealth = os.environ.get("OBSCURA_STEALTH", "false").lower() == "true"
        port = _resolve_port(os.environ.get("OBSCURA_PORT"))
        timeout = _resolve_timeout(os.environ.get("OBSCURA_STARTUP_TIMEOUT"))

        cmd = [binary, "serve", "--port", str(port)]
        if stealth:
            cmd.append("--stealth")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise RuntimeError(f"Failed to launch obscura: {exc}") from exc

        cdp_url = _await_cdp(port, proc, timeout)
        if cdp_url is None:
            _terminate(proc)
            raise RuntimeError(
                f"Obscura CDP server did not become ready on port {port} within "
                f"{timeout:g}s."
            )

        session_id = uuid.uuid4().hex
        with self._lock:
            self._procs[session_id] = proc

        session_name = f"hermes_{task_id}_{session_id[:8]}"
        features = {"stealth": stealth, "local": True}
        logger.info(
            "Started Obscura session %s (pid %s, port %s, stealth=%s)",
            session_name,
            proc.pid,
            port,
            stealth,
        )
        return {
            "session_name": session_name,
            "bb_session_id": session_id,
            "cdp_url": cdp_url,
            "features": features,
        }

    def _create_remote_session(self, task_id: str, base: str) -> Dict[str, object]:
        """Connect to an already-running obscura server (Docker/remote).

        The external server owns its lifecycle, so no process is spawned or
        tracked; close_session is a no-op for these sessions.
        """
        timeout = _resolve_timeout(os.environ.get("OBSCURA_STARTUP_TIMEOUT"))
        cdp_url = _await_remote_cdp(base, timeout)
        if cdp_url is None:
            raise RuntimeError(
                f"Obscura server at {base} did not respond on /json/version within "
                f"{timeout:g}s. Is `obscura serve` running and reachable there?"
            )
        session_id = uuid.uuid4().hex
        with self._lock:
            self._remote_sessions.add(session_id)
        session_name = f"hermes_{task_id}_{session_id[:8]}"
        logger.info(
            "Connected to remote Obscura session %s at %s", session_name, base
        )
        return {
            "session_name": session_name,
            "bb_session_id": session_id,
            "cdp_url": cdp_url,
            "features": {"stealth": None, "local": False, "remote": True},
        }

    def close_session(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._remote_sessions:
                # External server owns the lifecycle; nothing to tear down.
                self._remote_sessions.discard(session_id)
                return True
            proc = self._procs.pop(session_id, None)
        if proc is None:
            logger.debug("No Obscura process tracked for session %s", session_id)
            return False
        try:
            _terminate(proc)
            logger.debug("Closed Obscura session %s", session_id)
            return True
        except Exception as exc:  # never raise out of cleanup
            logger.error("Failed to close Obscura session %s: %s", session_id, exc)
            return False

    def emergency_cleanup(self, session_id: str) -> None:
        with self._lock:
            self._remote_sessions.discard(session_id)
            proc = self._procs.pop(session_id, None)
        if proc is None:
            return
        try:
            _terminate(proc)
        except Exception as exc:
            logger.debug(
                "Emergency cleanup failed for Obscura session %s: %s", session_id, exc
            )

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Obscura",
            "badge": "local",
            "tag": "Rust headless browser over CDP (local binary or remote/Docker server)",
            "env_vars": [
                {
                    "key": "OBSCURA_BIN",
                    "prompt": "Path to the obscura binary (optional if 'obscura' is on PATH)",
                    "url": "https://github.com/h4ckf0r0day/obscura",
                },
                {
                    "key": "OBSCURA_CDP_URL",
                    "prompt": "Connect to a running obscura server instead of spawning one (e.g. http://127.0.0.1:9222 for Docker)",
                    "url": "https://github.com/h4ckf0r0day/obscura",
                },
            ],
            "post_setup": "agent_browser",
        }


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _resolve_port(configured: Optional[str]) -> int:
    """Use OBSCURA_PORT when valid, else ask the OS for a free ephemeral port."""
    if configured:
        try:
            value = int(configured)
            if 1 <= value <= 65535:
                return value
        except ValueError:
            pass
        logger.warning(
            "Invalid OBSCURA_PORT %r; picking a free port instead", configured
        )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _resolve_timeout(configured: Optional[str]) -> float:
    if configured:
        try:
            value = float(configured)
            if value > 0:
                return value
        except ValueError:
            pass
        logger.warning(
            "Invalid OBSCURA_STARTUP_TIMEOUT %r; using %.0fs",
            configured,
            _DEFAULT_STARTUP_TIMEOUT,
        )
    return _DEFAULT_STARTUP_TIMEOUT


def _await_cdp(port: int, proc: subprocess.Popen, timeout: float) -> Optional[str]:
    """Poll ``/json/version`` until obscura is ready.

    Returns the ``webSocketDebuggerUrl`` (the CDP endpoint the agent connects
    to), or None if the process dies or the deadline passes.
    """
    deadline = time.monotonic() + timeout
    version_url = f"http://127.0.0.1:{port}/json/version"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return None  # process exited before serving
        try:
            resp = requests.get(version_url, timeout=1.0)
            if resp.ok:
                ws_url = resp.json().get("webSocketDebuggerUrl")
                if ws_url:
                    return ws_url
        except requests.RequestException:
            pass
        time.sleep(0.1)
    return None


def _remote_cdp_base() -> Optional[str]:
    """Return the normalized base URL for a remote obscura server, or None.

    Set via OBSCURA_CDP_URL. Accepts an ``http(s)://host:port`` or a
    ``ws(s)://`` endpoint (the scheme is normalized to http for the
    ``/json/version`` probe), with any ``/devtools/...`` or trailing path
    stripped so the base is just ``scheme://host:port``.
    """
    raw = os.environ.get("OBSCURA_CDP_URL", "").strip()
    if not raw:
        return None
    url = raw
    if url.startswith("ws://"):
        url = "http://" + url[len("ws://"):]
    elif url.startswith("wss://"):
        url = "https://" + url[len("wss://"):]
    elif not url.startswith(("http://", "https://")):
        url = "http://" + url
    # Keep only scheme://host:port.
    scheme, _, rest = url.partition("://")
    host_port = rest.split("/", 1)[0]
    return f"{scheme}://{host_port}"


def _await_remote_cdp(base: str, timeout: float) -> Optional[str]:
    """Poll a remote server's ``/json/version`` until it answers.

    Returns the ``webSocketDebuggerUrl``, or None if the deadline passes.
    Unlike the local poll there is no process to watch; we only wait for the
    endpoint to become reachable.
    """
    deadline = time.monotonic() + timeout
    version_url = f"{base}/json/version"
    # Parse OBSCURA_CDP_URL base so we can rewrite Obscura's hard-coded
    # ``webSocketDebuggerUrl`` (it always reports 127.0.0.1:9222 — useless
    # when served behind a reverse proxy like Traefik/Dokploy).
    from urllib.parse import urlparse
    parsed = urlparse(base)
    pub_host = parsed.hostname or ""
    pub_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    pub_scheme = "wss" if parsed.scheme == "https" else "ws"
    while time.monotonic() < deadline:
        try:
            resp = requests.get(version_url, timeout=2.0)
            if resp.ok:
                ws_url = resp.json().get("webSocketDebuggerUrl")
                if ws_url:
                    # Rewrite to public host/scheme so the CDP websocket
                    # goes through the proxy (TLS terminates at Traefik,
                    # 443 → upstream :9222 is routed by Dokploy config).
                    return f"{pub_scheme}://{pub_host}:{pub_port}/devtools/browser"
        except requests.RequestException:
            pass
        time.sleep(0.2)
    return None


def _terminate(proc: subprocess.Popen) -> None:
    """Terminate a process, escalating to kill after a short grace period."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
