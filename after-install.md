# Obscura plugin installed

Two steps to use it:

1. In `~/.hermes/.env`, set `OBSCURA_CDP_URL` for an existing local/remote
   server, or make sure the `obscura` binary is on PATH (optionally set
   `OBSCURA_BIN` to its path).
   Build it from https://github.com/h4ckf0r0day/obscura

2. Select it in your `config.yaml`:

   ```yaml
   browser:
     cloud_provider: "obscura"
   ```

For authenticated remote discovery, set `OBSCURA_TOKEN`; the proxy must return
an authenticated/signed WebSocket URL. Other optional env vars:
`OBSCURA_STEALTH`, `OBSCURA_PORT`, `OBSCURA_STARTUP_TIMEOUT`.
See the README for details.
