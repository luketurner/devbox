"""Invoke the pyinfra deploy, passing secrets via environment only."""
from __future__ import annotations

import subprocess
import time

INVENTORY = "deploy/inventory.py"
DEPLOY = "deploy/deploy.py"
# Hub is opt-in -- it costs ~1.5 GiB of images plus a running Postgres, which a
# devbox may prefer to leave to agent microVMs -- so it lives in its own pair of
# deploys rather than in DEPLOY. Driven by `devbox.py hub install/uninstall`.
HUB_INSTALL = "deploy/hub_install.py"
HUB_UNINSTALL = "deploy/hub_uninstall.py"

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


def build_pyinfra_args(deploy: str = DEPLOY) -> list[str]:
    # -y because pyinfra otherwise stops on "Detected changes ... skip this
    # step with -y" and reads stdin. These runs are driven by a CLI the user
    # already invoked deliberately, and without it a non-TTY caller dies on
    # EOFError -- which run_pyinfra would then retry twice more before failing.
    return ["pyinfra", "-y", INVENTORY, deploy,
            "--retry", str(OP_RETRIES),
            "--retry-delay", str(OP_RETRY_DELAY)]


def build_env(base: dict, *, host: str, ts_key: str, claude_token: str,
              agent_pool_size: int, agent_memory: int) -> dict:
    env = dict(base)
    env["DEVBOX_HOST"] = host
    env["DEVBOX_TS_AUTHKEY"] = ts_key
    env["CLAUDE_CODE_OAUTH_TOKEN"] = claude_token
    # Not secrets, but they travel the same way so the deploy has one source of
    # host data. str() because the environment has no other type.
    env["DEVBOX_AGENT_POOL_SIZE"] = str(agent_pool_size)
    env["DEVBOX_AGENT_MEMORY"] = str(agent_memory)
    return env


def build_hub_env(base: dict, *, host: str, owner_email: str | None = None,
                  owner_password: str | None = None) -> dict:
    """Environment for the hub deploys.

    The credentials are optional because uninstall has no use for them, and
    handing a teardown an owner password just to satisfy a signature is how
    secrets end up somewhere they need not be.
    """
    env = dict(base)
    env["DEVBOX_HOST"] = host
    if owner_email is not None:
        env["DEVBOX_HUB_OWNER_EMAIL"] = owner_email
    if owner_password is not None:
        env["DEVBOX_HUB_OWNER_PASSWORD"] = owner_password
    return env


def run_pyinfra(env: dict, *, deploy: str = DEPLOY,
                attempts: int = RUN_ATTEMPTS,
                delay: int = RUN_RETRY_DELAY,
                runner=subprocess.run, sleep=time.sleep):
    """Run the given deploy, retrying the whole run if it fails.

    Safe because every deploy here is idempotent: a repeat run skips what
    already succeeded, and the uninstall steps are guarded so a second pass is
    a no-op. A genuine failure still surfaces, just later.
    """
    args = build_pyinfra_args(deploy)
    for attempt in range(1, attempts + 1):
        result = runner(args, env=env)
        if result.returncode == 0:
            return result
        if attempt < attempts:
            print(f"pyinfra failed (attempt {attempt}/{attempts}); "
                  f"retrying in {delay}s — completed steps are skipped.")
            sleep(delay)
    raise subprocess.CalledProcessError(result.returncode, args)
