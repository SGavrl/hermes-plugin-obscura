# Obscura browser plugin for Hermes

Run [Hermes](https://github.com/NousResearch/hermes-agent) browser tasks on
[Obscura](https://github.com/h4ckf0r0day/obscura), a Rust headless browser that
speaks the Chrome DevTools Protocol without running Chrome or Chromium.

By default the plugin spawns `obscura serve` on a free local port and tears it
down when the session closes. It can also connect to an existing Obscura server.

## Why Obscura

- **Independent engine.** Obscura does not launch Chrome or Chromium underneath.
- **Simple deployment.** Run a local binary or connect to an Obscura container.
- **CDP-native.** It emulates headless Chrome over the DevTools Protocol, so the
  existing Hermes browser tools drive it unchanged.
- **Optional stealth.** A consistent browser fingerprint plus tracker blocking
  via `--stealth`.

## Install

1. For local mode, get the Obscura binary on the host: build it from
   [h4ckf0r0day/obscura](https://github.com/h4ckf0r0day/obscura) and put it on
   `PATH`, or point `OBSCURA_BIN` at it. Skip this step for remote mode.

2. Install the plugin:

   ```
   hermes plugins install SGavrl/hermes-plugin-obscura --enable
   ```

   If it is already installed but disabled, run:

   ```bash
   hermes plugins enable browser-obscura
   ```

3. Select it in `config.yaml`:

   ```yaml
   browser:
     cloud_provider: "obscura"
   ```

   It is opt-in and never auto-selected. When set, Hermes spawns `obscura serve`
   and routes browser tools through it.

## Two modes

**Local (default).** The plugin spawns `obscura serve` as a subprocess per
session and owns its lifecycle. Just have the binary on `PATH` or set
`OBSCURA_BIN`.

**Remote / Docker.** Point the plugin at an already-running `obscura serve` and
it connects instead of spawning. The external server owns its own lifecycle, so
the plugin never starts or stops it. The official image serves CDP on container
port 9222 by default:

```bash
docker run -d --name obscura -p 127.0.0.1:9222:9222 h4ckf0r0day/obscura
```

then set `OBSCURA_CDP_URL` in `~/.hermes/.env`:

```bash
OBSCURA_CDP_URL=http://127.0.0.1:9222
```

This is the way to scale Obscura independently of Hermes, or share one server
across sessions. No local binary is needed in this mode.

The CDP endpoint controls the browser and has no built-in authentication. Keep
it on loopback or a trusted private network; do not publish port 9222 directly
to the internet. For a server on another machine, an SSH tunnel is a simple
option:

```bash
ssh -L 9222:127.0.0.1:9222 user@obscura-host
```

## Configuration

All optional, via environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `OBSCURA_CDP_URL` | (unset) | Connect to a running server (remote mode). Unset means spawn locally. Accepts `http(s)://host:port` or a `ws(s)://` endpoint. |
| `OBSCURA_BIN` | `obscura` | Local mode: binary path, or a name resolved on `PATH`. |
| `OBSCURA_STEALTH` | `false` | Local mode: pass `--stealth` (consistent fingerprint + tracker blocking). |
| `OBSCURA_PERSIST_SESSION` | `false` | Local mode: persist cookies and localStorage in `<HERMES_HOME>/cache/obscura`. |
| `OBSCURA_PORT` | (ephemeral) | Local mode: fixed CDP port. Default asks the OS for a free port. |
| `OBSCURA_STARTUP_TIMEOUT` | `15` | Seconds to wait for the CDP server to come up. |

See `.env.example` and `config.yaml.example`.

Hermes currently treats every environment variable declared by a provider's
setup screen as required. Because `OBSCURA_BIN` and `OBSCURA_CDP_URL` are
optional alternatives, configure them manually rather than through that screen.

## Persist cookies and storage

Set `OBSCURA_PERSIST_SESSION=true` to pass
`--storage-dir <HERMES_HOME>/cache/obscura` when the plugin starts a local
server. Hermes resolves `HERMES_HOME` to the active profile home, or its
platform default when unset, so every profile keeps isolated browser state.
The option is off by default. It does not configure an `OBSCURA_CDP_URL`
server; pass `--storage-dir` when starting that server yourself.

```bash
# ~/.hermes/.env, or the active profile's .env
OBSCURA_PERSIST_SESSION=true
```

All local CDP sessions for that profile read and write the same directory.
Run Hermes under separate profiles for isolated browser identities.

### Layout

Inside `<HERMES_HOME>/cache/obscura`:

* `cookies.json`: cookie jar in a stable format with `same_site`, `expires`,
  `http_only`, and `secure`.
* `localStorage/<origin>.json`: one file per origin.

Inspect a cookie jar with `jq`:

```bash
jq '.[] | select(.domain == "example.com")' \
  "$HERMES_HOME/cache/obscura/cookies.json"
```

### When state is written

* On clean process exit (Ctrl-C, SIGTERM).
* After every navigation completes (CDP `Page.navigate`).
* Manually via CDP `Network.setCookie` and `Network.deleteCookies`.

### Clear state

Remove the profile-local directory:

```bash
rm -rf "$HERMES_HOME/cache/obscura"
```


### Direct Obscura CLI

For standalone Obscura use, choose a storage directory explicitly:

```bash
obscura fetch https://example.com --storage-dir ./obscura-data
obscura fetch https://example.com --storage-dir ./obscura-data
```

The second invocation starts with the cookies and localStorage left by the
first. To serve CDP clients with the same state:

```bash
obscura serve --storage-dir ./obscura-data
```

Run separate servers with different storage directories for isolated
identities:

```bash
obscura serve --port 9222 --storage-dir ./identity-a
obscura serve --port 9223 --storage-dir ./identity-b
```

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

For Hermes plugin installation and enablement, see the
[Hermes plugin guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins).

## Development

```
pip install -e ".[test]"
pytest
hermes plugins validate .
```

The tests use a real fake `obscura` binary (a small Python HTTP server that
serves `/json/version` like the real engine), so the full spawn, poll, and
teardown path is exercised without needing the Rust binary installed.

## License

Apache 2.0, matching the [Obscura](https://github.com/h4ckf0r0day/obscura) engine.
