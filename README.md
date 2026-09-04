# Obscura browser plugin for Hermes

Run [Hermes](https://github.com/NousResearch/hermes-agent) browser tasks on
[Obscura](https://github.com/h4ckf0r0day/obscura), a Rust headless browser that
speaks the Chrome DevTools Protocol with no Chrome or Node.js dependency. One
~70 MB binary, ~30 MB RAM at runtime, instant cold start.

The plugin can spawn a local `obscura serve` process or connect to an existing
local/remote CDP endpoint through `OBSCURA_CDP_URL`.

## Why Obscura

- **Light.** ~70 MB binary and ~30 MB RAM vs a full Chromium or Firefox, so you
  can run many concurrent agent sessions on one box.
- **No browser install.** No Chrome, Chromium, or Node to provision.
- **CDP-native.** It emulates headless Chrome over the DevTools Protocol, so the
  existing Hermes browser tools drive it unchanged.
- **Optional stealth.** A consistent browser fingerprint plus tracker blocking
  via `--stealth`.

## Install

1. For local mode, get the Obscura binary on the host: build it from
   [h4ckf0r0day/obscura](https://github.com/h4ckf0r0day/obscura) and put it on
   `PATH`, or point `OBSCURA_BIN` at it. Skip this for remote mode.

2. Install the plugin:

   ```
   hermes plugins install Company-OS-IA/hermes-obscura-plugin
   ```

3. Select it in `config.yaml`:

   ```yaml
   browser:
     cloud_provider: "obscura"
   ```

   It is opt-in and never auto-selected. Hermes then routes browser tools
   through the local or remote Obscura endpoint.

## Two modes

**Local (default).** The plugin spawns `obscura serve` as a subprocess per
session and owns its lifecycle. Just have the binary on `PATH` or set
`OBSCURA_BIN`.

**Remote / Docker.** Point the plugin at an already-running `obscura serve` and
it connects instead of spawning. The external server owns its own lifecycle, so
the plugin never starts or stops it. The official image already serves CDP on
`0.0.0.0:9222` by default:

```bash
docker run -d -p 9222:9222 h4ckf0r0day/obscura
```

then set the environment in `~/.hermes/.env`:

```bash
OBSCURA_CDP_URL=http://127.0.0.1:9222
```

This is the way to scale Obscura independently of Hermes, or share one server
across sessions. No local binary is needed in this mode.

## Configuration

All optional, via environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `OBSCURA_CDP_URL` | (unset) | Remote server base URL. Unset or blank means spawn locally. Accepts `http(s)://host:port`; `ws(s)://` is also accepted and normalized for `/json/version` discovery. |
| `OBSCURA_TOKEN` | (unset) | Optional Bearer token sent to `/json/version`. The proxy must return a signed/authenticated WebSocket URL. |
| `OBSCURA_BIN` | `obscura` | Local mode: binary path, or a name resolved on `PATH`. Blank also uses `obscura`. |
| `OBSCURA_STEALTH` | `false` | Local mode: pass `--stealth` (consistent fingerprint + tracker blocking). |
| `OBSCURA_PORT` | (ephemeral) | Local mode: fixed CDP port. Default asks the OS for a free port. |
| `OBSCURA_STARTUP_TIMEOUT` | `15` | Seconds to wait for the CDP server to come up. |

Set these values in `~/.hermes/.env` (or the Hermes process environment). The
Hermes provider picker does not currently represent optional either/or fields,
so it intentionally does not prompt for `OBSCURA_BIN` and `OBSCURA_CDP_URL`.
See `.env.example` and `config.yaml.example`.

### Authenticated reverse proxy

Use HTTPS when the remote endpoint requires authentication:

```bash
OBSCURA_CDP_URL=https://browser.example.com
OBSCURA_TOKEN=your-bearer-token
```

The plugin sends `Authorization: Bearer <token>` only to
`GET /json/version`. That response must contain a reachable, signed or otherwise
authenticated `webSocketDebuggerUrl`; Hermes connects to that URL without custom
headers. If Obscura advertises a loopback address, the plugin replaces only its
scheme and authority with `OBSCURA_CDP_URL`, preserving the path and query string.
Plain HTTP with a token is accepted only for localhost.

## How it works

`ObscuraBrowserProvider` implements the Hermes
[`BrowserProvider`](https://hermes-agent.nousresearch.com/docs/developer-guide/browser-provider-plugin)
lifecycle:

- `create_session` (local mode) spawns `obscura serve --port <free>` (plus
  `--stealth` if enabled), polls `/json/version` until the CDP server answers,
  and returns the `webSocketDebuggerUrl` for the agent to connect to.
- `create_session` (remote mode, `OBSCURA_CDP_URL` set) polls the given server's
  `/json/version` and returns its `webSocketDebuggerUrl`, without spawning
  anything.
- `close_session` and `emergency_cleanup` terminate the owning process in local
  mode (SIGTERM, then kill after a grace period), and are no-ops in remote mode
  since the external server owns its lifecycle.

The plugin touches no Hermes core files. It registers through the standard
plugin entry point (`register(ctx)` calling `ctx.register_browser_provider`).

## Development

```
pip install -e ".[test]"
pytest
```

The tests use a real fake `obscura` binary (a small Python HTTP server that
serves `/json/version` like the real engine), so the full spawn, poll, and
teardown path is exercised without needing the Rust binary installed.

## License

Apache 2.0, matching the [Obscura](https://github.com/h4ckf0r0day/obscura) engine.
