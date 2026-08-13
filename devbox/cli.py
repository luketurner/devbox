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

from devbox import claude_auth, config, exe, paseo, provision, tailscale

ACCOUNT_REQUIRED = ["exe_vm_name",
                    "ts_oauth_client_id", "ts_oauth_client_secret",
                    "ts_tailnet", "ts_tag",
                    "hub_owner_email", "hub_owner_password"]


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
    sub = p.add_subparsers(dest="command", required=True)

    prov = sub.add_parser("provision", help="create and provision the devbox VM")
    prov.add_argument("--vm-name", help="exe.dev VM name (overrides the cached one)")

    add = sub.add_parser("add-repo", help="enable a GitHub repo as a Paseo project")
    add.add_argument("repo_spec", help="GitHub repo as user/repo")

    return p.parse_args(argv)


def preflight(tools=("ssh", "claude")) -> list[str]:
    return [tool for tool in tools if shutil.which(tool) is None]


def _prompt(field: str, secret: bool = False) -> str:
    import questionary
    ask = questionary.password if secret else questionary.text
    value = ask(f"{field}: ").ask()
    if value is None:
        print(f"aborted: no value for {field}", file=sys.stderr)
        raise SystemExit(1)
    return value


def _resolve_account_config(required=None, overrides=None) -> dict:
    """Load the account config, applying CLI overrides and prompting for gaps.

    `required` is narrowed by add-repo so it doesn't interrogate the user for
    Tailscale creds and a Hub password it will never use.
    """
    acct = config.load_toml(config.ACCOUNT_PATH)
    # merge skips None/"", so an omitted flag keeps the cached value.
    merged = config.merge(acct, overrides or {})
    for field in config.missing_fields(merged, required or ACCOUNT_REQUIRED):
        merged[field] = _prompt(field, secret=field.endswith(("secret", "password")))
    if merged != acct:
        config.save_toml(config.ACCOUNT_PATH, merged)
    return merged


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


def _cmd_provision(ns) -> int:
    missing = preflight()
    if missing:
        print(f"Missing required tools on PATH: {', '.join(missing)}",
              file=sys.stderr)
        return 1

    account = _resolve_account_config(overrides={"exe_vm_name": ns.vm_name})

    # Claude token (local browser login once), cached in account config.
    token = claude_auth.ensure_token(account.get("claude_token"))
    if token != account.get("claude_token"):
        account["claude_token"] = token
        config.save_toml(config.ACCOUNT_PATH, account)

    name = account["exe_vm_name"]
    host = exe.vm_host(name)

    # exe.dev VM (create-if-missing).
    if not exe.vm_exists(exe.list_vms(), name):
        print(f"Creating VM {name}...")
        exe.create_vm(name, ["dev"])

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
                              claude_token=token,
                              hub_owner_email=account["hub_owner_email"],
                              hub_owner_password=account["hub_owner_password"])
    provision.run_pyinfra(env)

    print(f"Done. Provisioned {host}.")
    print("Paseo daemon (6767) and Hub (3000) are on the tailnet — "
          "see the README to pair.")
    return 0


def _cmd_add_repo(ns) -> int:
    missing = preflight(("ssh",))
    if missing:
        print(f"Missing required tools on PATH: {', '.join(missing)}",
              file=sys.stderr)
        return 1

    user, repo = split_repo(ns.repo_spec)
    account = _resolve_account_config(required=["exe_vm_name"])
    vm_name = account["exe_vm_name"]
    host = exe.vm_host(vm_name)

    # exe.dev integration (create-if-missing), attached to the one VM.
    name = exe.integration_name(user, repo)
    if not exe.integration_exists(exe.list_integrations(), name):
        print(f"Creating GitHub integration {name} attached to vm:{vm_name}...")
        exe.add_integration(user, repo, vm_name)

    print(f"Registering {user}/{repo} as a Paseo workspace on {host}...")
    result = subprocess.run(["ssh", host, paseo.build_clone_cmd(user, repo)])
    if result.returncode != 0:
        return result.returncode

    print(f"Done. {user}/{repo} is available in Paseo under {paseo.CLONE_DIR}.")
    return 0


def main(argv=None) -> int:
    ns = parse_args(sys.argv[1:] if argv is None else argv)
    if ns.command == "add-repo":
        return _cmd_add_repo(ns)
    return _cmd_provision(ns)
