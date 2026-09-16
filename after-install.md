# Obscura plugin installed

Three steps to use it:

1. For local mode, make sure the `obscura` binary is on PATH, or set
   `OBSCURA_BIN` to its path. Build it from
   https://github.com/h4ckf0r0day/obscura. For remote mode, set
   `OBSCURA_CDP_URL` instead.

2. Enable the plugin if it was not installed with `--enable`:

   ```bash
   hermes plugins enable browser-obscura
   ```

3. Select it in your `config.yaml`:

   ```yaml
   browser:
     cloud_provider: "obscura"
   ```

Optional env vars: `OBSCURA_STEALTH`, `OBSCURA_PERSIST_SESSION`,
`OBSCURA_PORT`, and `OBSCURA_STARTUP_TIMEOUT`. See the README for details and
network safety notes.
