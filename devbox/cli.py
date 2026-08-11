"""devbox orchestrator: create exe.dev integration + VM, provision via pyinfra."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time

import httpx

from devbox import claude_auth, config, exe, provision, session, tailscale

ACCOUNT_REQUIRED = ["ts_oauth_client_id", "ts_oauth_client_secret",
                    "ts_tailnet", "ts_tag",
                    "hub_owner_email", "hub_owner_password"]
REPO_REQUIRED = ["github_user", "repo_name", "exe_prefix"]


_USER_REPO_RE = re.compile(r"[A-Za-z0-9._-]+")


def split_repo(spec: str) -> tuple[str, str]:
    if "/" not in spec:
        raise ValueError(f"expected user/repo, got: {spec!r}")
    user, repo = spec.split("/", 1)
    if not user or not repo:
        raise ValueError(f"expected user/repo, got: {spec!r}")
    if not _USER_REPO_RE.fullmatch(user) or not _USER_REPO_RE.fullmatch(repo):
        raise ValueError(f"invalid user/repo: {spec!r}")
    return user, repo


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="devbox")
    p.add_argument("repo_spec", help="GitHub repo as user/repo")
    p.add_argument("--prefix", help="exe.dev VM name prefix")
    return p.parse_args(argv)


def preflight() -> list[str]:
    return [tool for tool in ("ssh", "claude", "git")
            if shutil.which(tool) is None]


def _prompt(field: str, secret: bool = False) -> str:
    import questionary
    ask = questionary.password if secret else questionary.text
    value = ask(f"{field}: ").ask()
    if value is None:
        print(f"aborted: no value for {field}", file=sys.stderr)
        raise SystemExit(1)
    return value


def _resolve_repo_config(user, repo, prefix) -> dict:
    cached = config.load_toml(config.repo_config_path(repo))
    cli_layer = {"github_user": user, "repo_name": repo, "exe_prefix": prefix}
    merged = config.merge(cached, cli_layer)
    for field in config.missing_fields(merged, REPO_REQUIRED):
        merged[field] = _prompt(field)
    config.save_toml(config.repo_config_path(repo), merged)
    return merged


def _resolve_account_config() -> dict:
    acct = config.load_toml(config.ACCOUNT_PATH)
    changed = False
    for field in config.missing_fields(acct, ACCOUNT_REQUIRED):
        acct[field] = _prompt(field, secret=field.endswith(("secret", "password")))
        changed = True
    if changed:
        config.save_toml(config.ACCOUNT_PATH, acct)
    return acct


def _ssh_ready(host: str) -> bool:
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "true"],
        capture_output=True,
    )
    return result.returncode == 0


def _wait_for_ssh(host: str, timeout=300) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _ssh_ready(host):
            return
        time.sleep(5)
    raise TimeoutError(f"SSH to {host} not ready within {timeout}s")


def main(argv=None) -> int:
    ns = parse_args(sys.argv[1:] if argv is None else argv)
    missing = preflight()
    if missing:
        print(f"Missing required tools on PATH: {', '.join(missing)}",
              file=sys.stderr)
        return 1

    user, repo = split_repo(ns.repo_spec)
    account = _resolve_account_config()
    repo_cfg = _resolve_repo_config(user, repo, ns.prefix)

    # Claude token (local browser login once), cached in account config.
    token = claude_auth.ensure_token(account.get("claude_token"))
    if token != account.get("claude_token"):
        account["claude_token"] = token
        config.save_toml(config.ACCOUNT_PATH, account)

    name = f"{repo_cfg['exe_prefix']}-{repo}"
    host = exe.vm_host(repo_cfg["exe_prefix"], repo)

    # exe.dev integration (create-if-missing).
    if not exe.integration_exists(exe.list_integrations(), repo):
        print(f"Creating GitHub integration for {user}/{repo}...")
        exe.add_integration(user, repo)

    # exe.dev VM (create-if-missing).
    if not exe.vm_exists(exe.list_vms(), name):
        print(f"Creating VM {name}...")
        exe.create_vm(name, ["dev", repo])

    print(f"Waiting for SSH to {host}...")
    _wait_for_ssh(host)

    # Fresh ephemeral Tailscale key per run.
    print("Minting Tailscale auth key...")
    with httpx.Client(base_url=tailscale.TS_API, timeout=30) as client:
        ts_key = tailscale.mint_key(
            account["ts_tailnet"], account["ts_tag"],
            account["ts_oauth_client_id"], account["ts_oauth_client_secret"],
            client=client,
        )

    # Provision via pyinfra (secrets via env).
    print("Provisioning via pyinfra...")
    env = provision.build_env(dict(os.environ), host=host, ts_key=ts_key,
                              claude_token=token, repo=repo,
                              hub_owner_email=account["hub_owner_email"],
                              hub_owner_password=account["hub_owner_password"])
    provision.run_pyinfra(env)

    # Start detached claude session (idempotent).
    print("Starting detached claude session...")
    subprocess.run(["ssh", host, session.build_start_session_cmd(repo)],
                   check=True)

    print(f"Done. Connect with:  ssh {host} herdr attach devbox")
    return 0
