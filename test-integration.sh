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
# Safe to re-run. Everything Hermes-side goes under ~/.hermes; nothing else on
# the box is touched. The script never installs Hermes for you if it is missing;
# it tells you the one command to run and stops, so you stay in control of that.

set -uo pipefail

PLUGIN_REPO="Company-OS-IA/hermes-obscura-plugin"
PLUGIN_NAME="browser-obscura"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- pretty output ---------------------------------------------------------
c_g=$'\033[32m'; c_r=$'\033[31m'; c_y=$'\033[33m'; c_b=$'\033[36m'; c_0=$'\033[0m'
pass(){ echo "${c_g}PASS${c_0} $*"; }
fail(){ echo "${c_r}FAIL${c_0} $*"; }
info(){ echo "${c_b}--->${c_0} $*"; }
warn(){ echo "${c_y}NOTE${c_0} $*"; }
hr(){ echo "------------------------------------------------------------"; }
die(){ fail "$*"; echo; echo "Stopped at the first failure. Fix the above and re-run."; exit 1; }

RUN_TMP="$(mktemp -d)" || die "could not create temporary directory"
SPID=""
cleanup() {
    if [ -n "$SPID" ]; then kill "$SPID" 2>/dev/null; wait "$SPID" 2>/dev/null; fi
    rm -rf -- "$RUN_TMP"
}
trap cleanup EXIT

# ===========================================================================
hr; echo "LEVEL 0 — plugin's own tests (no Hermes, no key)"; hr
# ===========================================================================
if ! command -v python3 >/dev/null 2>&1; then die "python3 not found"; fi
info "installing test deps into a throwaway venv"
VENV="$RUN_TMP/venv"
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
SPORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')
SMOKE_LOG="$RUN_TMP/obscura-smoke.log"
CDP_JSON="$RUN_TMP/cdp.json"
"$OBSCURA" serve --port "$SPORT" >"$SMOKE_LOG" 2>&1 &
SPID=$!
for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$SPORT/json/version" >"$CDP_JSON" 2>/dev/null; then break; fi
    sleep 0.3
done
if grep -q webSocketDebuggerUrl "$CDP_JSON" 2>/dev/null; then
    pass "obscura CDP endpoint is live: $(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("webSocketDebuggerUrl",""))' "$CDP_JSON")"
else
    cat "$SMOKE_LOG"
    die "obscura serve did not expose a CDP endpoint"
fi
kill "$SPID" 2>/dev/null; wait "$SPID" 2>/dev/null
SPID=""

# ===========================================================================
hr; echo "LEVEL 2 — Hermes install + register + spawn"; hr
# ===========================================================================
if ! command -v hermes >/dev/null 2>&1; then
    warn "Hermes is not installed on this box."
    echo
    echo "  Install it (their official installer), then re-run this script:"
    echo "     ${c_b}curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash${c_0}"
    echo
    echo "  Levels 0 and 1 already passed, so the plugin and engine are good."
    echo "  Level 2 needs Hermes present; stopping here without failing."
    exit 0
fi
info "hermes found: $(command -v hermes)"

info "installing the plugin from ${PLUGIN_REPO}"
PLUGIN_LOG="$RUN_TMP/plugin-install.log"
if hermes plugins install "$PLUGIN_REPO" --yes 2>"$PLUGIN_LOG" || hermes plugins install "$PLUGIN_REPO" 2>"$PLUGIN_LOG"; then
    pass "hermes plugins install ran"
else
    cat "$PLUGIN_LOG"
    die "hermes plugins install failed. See $PLUGIN_LOG for details."
fi

info "checking it registered"
if hermes plugins list 2>/dev/null | grep -qi "obscura"; then
    pass "plugin appears in 'hermes plugins list'"
    hermes plugins list 2>/dev/null | grep -i obscura
else
    warn "plugin not shown in 'hermes plugins list' — it may need enabling:"
    echo "     hermes plugins enable ${PLUGIN_NAME}"
fi

# confirm the provider registers and can be selected. This does NOT need a model:
# we import the provider through Hermes and drive its create_session directly.
info "confirming the browser provider registers and spawns obscura (no LLM)"
export OBSCURA_BIN="$OBSCURA"
if python3 - "$OBSCURA" <<'PY'
import os, sys, importlib, time, json, urllib.request
# Ask Hermes for its browser registry and pull the obscura provider out of it.
try:
    from agent import browser_registry as reg
except Exception as e:
    print("FAIL could not import agent.browser_registry: %s" % e)
    sys.exit(1)

# Force plugin discovery the same way a Hermes run would.
try:
    from hermes_cli import plugins as hp
    for fn in ("load_plugins","discover_and_register","load_all"):
        if hasattr(hp, fn):
            try: getattr(hp, fn)()
            except Exception: pass
except Exception:
    pass

providers = getattr(reg, "_providers", {})
prov = providers.get("obscura")
if prov is None:
    print("FAIL 'obscura' provider not in registry. Enable the plugin and re-run.")
    print("     Registered:", list(providers))
    sys.exit(1)

print("--->  provider registered:", type(prov).__name__)
if not prov.is_available():
    print("FAIL provider.is_available() is False — check OBSCURA_BIN"); sys.exit(1)

sess = prov.create_session("smoke-task")
print("--->  create_session returned:", json.dumps(sess)[:200])
cdp = sess.get("cdp_url") or sess.get("cdpUrl") or sess.get("connect_url") or ""
sid = sess.get("bb_session_id")
ok = False
if cdp:
    base = cdp.replace("ws://","http://").split("/devtools")[0]
    try:
        with urllib.request.urlopen(base + "/json/version", timeout=3) as r:
            ok = b"webSocketDebuggerUrl" in r.read()
    except Exception as e:
        print("NOTE could not curl the returned CDP endpoint:", e)
print(("PASS" if ok else "NOTE"), "obscura spawned via Hermes provider; CDP reachable =", ok)
try:
    if not sid or not prov.close_session(sid):
        print("FAIL close_session did not close the provider session"); sys.exit(1)
    print("--->  close_session ok")
except Exception as e:
    print("FAIL close_session raised:", e); sys.exit(1)
if not ok:
    sys.exit(1)
PY
then
    pass "Hermes registered Obscura and completed the CDP lifecycle"
else
    die "Hermes provider integration failed"
fi

echo
hr; echo "DONE"; hr
echo "Levels 0-1 verify the plugin and engine. Level 2 verifies Hermes loads it,"
echo "registers the provider, and spawns obscura over CDP — all without an API key."
echo
echo "Level 3 (optional, needs a model): set in config.yaml"
echo "     browser:"
echo "       cloud_provider: \"obscura\""
echo "   then run a real browser task and watch the agent drive obscura."
