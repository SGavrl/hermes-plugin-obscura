# Obscura plugin installed

Two steps to use it:

1. Make sure the `obscura` binary is on PATH, or set `OBSCURA_BIN` to its path.
   Build it from https://github.com/h4ckf0r0day/obscura

2. Select it in your `config.yaml`:

   ```yaml
   browser:
     cloud_provider: "obscura"
   ```

Optional env vars: `OBSCURA_STEALTH`, `OBSCURA_PORT`, `OBSCURA_STARTUP_TIMEOUT`.
See the README for details.
