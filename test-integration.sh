#!/usr/bin/env bash
#
# test-integration.sh — validate the Obscura Hermes plugin end to end.
#
# Runs in staged levels, cheapest and most certain first. No API key is needed
# for Levels 0-2 (Level 3, a real agent task, needs a model and is left to you).
#
#   Level 0  plugin's own pytest suite (no Hermes, no key)
#   Level 1  obscura binary sanity
#   Level 2  install into Hermes, confirm it registers, confirm it spawns
#            `obscura serve` and hands back a live CDP endpoint
#
# Usage:
#   OBSCURA_BIN=/path/to/obscura ./test-integration.sh
#   (or put `obscura` on PATH first)
#
# Safe to re-run. The installed plugin copy is refreshed from GitHub. The script
# never installs Hermes for you if it is missing; it reports that and stops.

set -uo pipefail

PLUGIN_REPO="${PLUGIN_REPO:-SGavrl/hermes-plugin-obscura}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR="$(mktemp -d)"
VENV="$TMP_DIR/venv"
SPID=""

cleanup() {
    if [ -n "$SPID" ]; then
        kill "$SPID" 2>/dev/null || true
        wait "$SPID" 2>/dev/null || true
    fi
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

# ---- pretty output ---------------------------------------------------------
c_g=$'\033[32m'; c_r=$'\033[31m'; c_y=$'\033[33m'; c_b=$'\033[36m'; c_0=$'\033[0m'
pass(){ echo "${c_g}PASS${c_0} $*"; }
fail(){ echo "${c_r}FAIL${c_0} $*"; }
info(){ echo "${c_b}--->${c_0} $*"; }
warn(){ echo "${c_y}NOTE${c_0} $*"; }
hr(){ echo "------------------------------------------------------------"; }
die(){ fail "$*"; echo; echo "Stopped at the first failure. Fix the above and re-run."; exit 1; }

# ===========================================================================
hr; echo "LEVEL 0 — plugin's own tests (no Hermes, no key)"; hr
# ===========================================================================
if ! command -v python3 >/dev/null 2>&1; then die "python3 not found"; fi
info "installing test deps into a throwaway venv"
python3 -m venv "$VENV" || die "could not create venv (need python3-venv)"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q -e "${SCRIPT_DIR}[test]" 2>/dev/null || pip install -q pytest requests || die "pip install failed"
info "running pytest"
if (cd "$SCRIPT_DIR" && python -m pytest -q); then
    pass "plugin unit tests green (spawn/poll/teardown logic verified)"
else
    die "plugin unit tests failed — the repo itself has a problem, fix before touching Hermes"
fi
deactivate

# ===========================================================================
hr; echo "LEVEL 1 — obscura binary sanity"; hr
# ===========================================================================
OBSCURA="${OBSCURA_BIN:-$(command -v obscura || true)}"
if [ -z "$OBSCURA" ] || [ ! -x "$OBSCURA" ]; then
    die "obscura binary not found. Put it on PATH or set OBSCURA_BIN=/path/to/obscura
     Build it from https://github.com/h4ckf0r0day/obscura"
fi
info "obscura at: $OBSCURA"
"$OBSCURA" --version >/dev/null 2>&1 && pass "obscura runs ($($OBSCURA --version 2>&1 | head -1))" || warn "obscura --version returned nonzero (older build?), continuing"

# quick standalone CDP smoke: start serve, curl /json/version, stop
info "smoke test: obscura serve + CDP /json/version"
SPORT=$(python3 - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)
"$OBSCURA" serve --port "$SPORT" >"$TMP_DIR/obscura-smoke.log" 2>&1 &
SPID=$!
for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$SPORT/json/version" >"$TMP_DIR/cdp.json" 2>/dev/null; then break; fi
    sleep 0.3
done
if grep -q webSocketDebuggerUrl "$TMP_DIR/cdp.json" 2>/dev/null; then
    pass "obscura CDP endpoint is live: $(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("webSocketDebuggerUrl",""))' "$TMP_DIR/cdp.json")"
else
    die "obscura serve did not expose a CDP endpoint — see $TMP_DIR/obscura-smoke.log"
fi
kill "$SPID" 2>/dev/null; wait "$SPID" 2>/dev/null
SPID=""

# ===========================================================================
hr; echo "LEVEL 2 — Hermes install + register + spawn"; hr
# ===========================================================================
if ! command -v hermes >/dev/null 2>&1; then
    warn "Hermes is not installed on this box."
    echo
    echo "  Install it using the official instructions, then re-run this script:"
    echo "     ${c_b}https://hermes-agent.nousresearch.com/docs/getting-started/installation${c_0}"
    echo
    echo "  Levels 0 and 1 already passed, so the plugin and engine are good."
    echo "  Level 2 needs Hermes present; stopping here without failing."
    exit 0
fi
info "hermes found: $(command -v hermes)"

info "validating this checkout with Hermes"
if hermes plugins validate "$SCRIPT_DIR" >"$TMP_DIR/plugin-validate.log" 2>&1; then
    pass "hermes plugins validate passed"
else
    cat "$TMP_DIR/plugin-validate.log"
    die "hermes plugins validate failed"
fi

info "installing and enabling the plugin from ${PLUGIN_REPO}"
if hermes plugins install "$PLUGIN_REPO" --force --enable >"$TMP_DIR/plugin-install.log" 2>&1; then
    pass "plugin installed and enabled"
else
    cat "$TMP_DIR/plugin-install.log"
    die "hermes plugins install failed"
fi

# Confirm the enabled plugin registers and can create a session. This does not
# need a model; it uses Hermes's supported discovery and registry APIs.
info "confirming the provider registers, spawns, and closes Obscura (no LLM)"
export OBSCURA_BIN="$OBSCURA"
HERMES_PYTHON="${HERMES_PYTHON:-python3}"
if ! "$HERMES_PYTHON" -c 'import hermes_cli' >/dev/null 2>&1; then
    die "${HERMES_PYTHON} cannot import Hermes; set HERMES_PYTHON to the Python used by the hermes command"
fi
"$HERMES_PYTHON" <<'PY'
import json
import sys
import urllib.request
from urllib.parse import urlsplit, urlunsplit

try:
    from agent.browser_registry import get_provider, list_providers
    from hermes_cli.plugins import discover_plugins
except Exception as exc:
    print("FAIL could not import current Hermes plugin APIs:", exc)
    sys.exit(1)

try:
    discover_plugins(force=True)
except Exception as exc:
    print("FAIL Hermes plugin discovery failed:", exc)
    sys.exit(1)
provider = get_provider("obscura")
if provider is None:
    print("FAIL 'obscura' did not register; registered:", [p.name for p in list_providers()])
    sys.exit(1)
if not provider.is_available():
    print("FAIL provider.is_available() is false; check OBSCURA_BIN")
    sys.exit(1)

session = None
failed = False
try:
    session = provider.create_session("smoke-task")
    cdp_url = session.get("cdp_url")
    session_id = session.get("bb_session_id")
    if not isinstance(cdp_url, str) or not cdp_url:
        raise RuntimeError("create_session did not return cdp_url")
    if not isinstance(session_id, str) or not session_id:
        raise RuntimeError("create_session did not return bb_session_id")

    parsed = urlsplit(cdp_url)
    version_url = urlunsplit(
        ({"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme),
         parsed.netloc, "/json/version", "", "")
    )
    with urllib.request.urlopen(version_url, timeout=3) as response:
        payload = json.load(response)
    if not payload.get("webSocketDebuggerUrl"):
        raise RuntimeError("/json/version did not return webSocketDebuggerUrl")
    print("--->  provider registered:", type(provider).__name__)
    print("--->  create_session returned:", json.dumps(session, sort_keys=True)[:240])
    print("PASS Obscura CDP endpoint is reachable")
except Exception as exc:
    failed = True
    print("FAIL provider lifecycle:", exc)
finally:
    if session is not None:
        session_id = session.get("bb_session_id")
        if not session_id or not provider.close_session(session_id):
            failed = True
            print("FAIL close_session did not close the provider session")
        else:
            print("PASS close_session closed the provider session")

sys.exit(1 if failed else 0)
PY

echo
hr; echo "DONE"; hr
echo "Levels 0-1 verify the plugin and engine. Level 2 verifies Hermes loads it,"
echo "registers the provider, and spawns obscura over CDP — all without an API key."
echo
echo "Level 3 (optional, needs a model): set in config.yaml"
echo "     browser:"
echo "       cloud_provider: \"obscura\""
echo "   then run a real browser task and watch the agent drive obscura."
