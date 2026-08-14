"""Invoke the pyinfra deploy, passing secrets via environment only."""
from __future__ import annotations

import subprocess
import time

INVENTORY = "deploy/inventory.py"
DEPLOY = "deploy/deploy.py"

# Connections through the exe.dev proxy drop mid-run often enough to matter:
# a channel dies, the operation reports "Command socket/SSH error", and pyinfra
# gives up on the host. Two layers of recovery, because they catch different
# failures. --retry re-runs the failed operation in-process, which handles a
# dead *channel*; a whole new pyinfra run gets a fresh connection, which is the
# only thing that helps when the *transport* is gone.
OP_RETRIES = 2
OP_RETRY_DELAY = 5
RUN_ATTEMPTS = 3
RUN_RETRY_DELAY = 10


def build_pyinfra_args() -> list[str]:
    return ["pyinfra", INVENTORY, DEPLOY,
            "--retry", str(OP_RETRIES),
            "--retry-delay", str(OP_RETRY_DELAY)]


def build_env(base: dict, *, host: str, ts_key: str, claude_token: str,
              hub_owner_email: str, hub_owner_password: str) -> dict:
    env = dict(base)
    env["DEVBOX_HOST"] = host
    env["DEVBOX_TS_AUTHKEY"] = ts_key
    env["CLAUDE_CODE_OAUTH_TOKEN"] = claude_token
    env["DEVBOX_HUB_OWNER_EMAIL"] = hub_owner_email
    env["DEVBOX_HUB_OWNER_PASSWORD"] = hub_owner_password
    return env


def run_pyinfra(env: dict, *, attempts: int = RUN_ATTEMPTS,
                delay: int = RUN_RETRY_DELAY,
                runner=subprocess.run, sleep=time.sleep):
    """Run the deploy, retrying the whole run if it fails.

    Safe because the deploy is idempotent: a repeat run skips everything that
    already succeeded. A genuine failure still surfaces, just later.
    """
    args = build_pyinfra_args()
    for attempt in range(1, attempts + 1):
        result = runner(args, env=env)
        if result.returncode == 0:
            return result
        if attempt < attempts:
            print(f"pyinfra failed (attempt {attempt}/{attempts}); "
                  f"retrying in {delay}s — completed steps are skipped.")
            sleep(delay)
    raise subprocess.CalledProcessError(result.returncode, args)
