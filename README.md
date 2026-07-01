# Obscura browser plugin for Hermes

Run [Hermes](https://github.com/NousResearch/hermes-agent) browser tasks on
[Obscura](https://github.com/h4ckf0r0day/obscura), a Rust headless browser that
speaks the Chrome DevTools Protocol with no Chrome or Node.js dependency. One
~70 MB binary, ~30 MB RAM at runtime, instant cold start.

This is a **local** browser backend. Instead of calling a cloud API, the plugin
spawns `obscura serve` on a free port and hands the agent that process's CDP
endpoint, one process per session, torn down on session close.

## Why Obscura

- **Light.** ~70 MB binary and ~30 MB RAM vs a full Chromium or Firefox, so you
  can run many concurrent agent sessions on one box.
- **No browser install.** No Chrome, Chromium, or Node to provision.
- **CDP-native.** It emulates headless Chrome over the DevTools Protocol, so the
  existing Hermes browser tools drive it unchanged.
- **Optional stealth.** A consistent browser fingerprint plus tracker blocking
  via `--stealth`.

## Install

1. Get the Obscura binary on the host: build it from
   [h4ckf0r0day/obscura](https://github.com/h4ckf0r0day/obscura) and put it on
   `PATH`, or point `OBSCURA_BIN` at it.

2. Install the plugin:

   ```
   hermes plugins install SGavrl/hermes-plugin-obscura
   ```

3. Select it in `config.yaml`:

   ```yaml
   browser:
     cloud_provider: "obscura"
   ```

   It is opt-in and never auto-selected. When set, Hermes spawns `obscura serve`
   and routes browser tools through it.

## Configuration

All optional, via environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `OBSCURA_BIN` | `obscura` | Binary path, or a name resolved on `PATH`. |
| `OBSCURA_STEALTH` | `false` | Pass `--stealth` (consistent fingerprint + tracker blocking). |
| `OBSCURA_PORT` | (ephemeral) | Fixed CDP port. Default asks the OS for a free port. |
| `OBSCURA_STARTUP_TIMEOUT` | `15` | Seconds to wait for the CDP server to come up. |

See `env.example` and `config.yaml.example`.

## How it works

`ObscuraBrowserProvider` implements the Hermes
[`BrowserProvider`](https://github.com/NousResearch/hermes-agent/blob/main/agent/browser_provider.py)
lifecycle:

- `create_session` spawns `obscura serve --port <free>` (plus `--stealth` if
  enabled), polls `/json/version` until the CDP server answers, and returns the
  `webSocketDebuggerUrl` for the agent to connect to.
- `close_session` and `emergency_cleanup` terminate the owning process
  (SIGTERM, then kill after a grace period).

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

MIT
