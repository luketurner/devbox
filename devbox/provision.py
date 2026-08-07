"""Invoke the pyinfra deploy, passing secrets via environment only."""
from __future__ import annotations

import subprocess

INVENTORY = "deploy/inventory.py"
DEPLOY = "deploy/deploy.py"


def build_pyinfra_args() -> list[str]:
    return ["pyinfra", INVENTORY, DEPLOY]


def build_env(base: dict, *, host: str, ts_key: str, claude_token: str,
              repo: str) -> dict:
    env = dict(base)
    env["DEVBOX_HOST"] = host
    env["DEVBOX_TS_AUTHKEY"] = ts_key
    env["CLAUDE_CODE_OAUTH_TOKEN"] = claude_token
    env["DEVBOX_REPO"] = repo
    return env


def run_pyinfra(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(build_pyinfra_args(), env=env, check=True)
