"""devbox orchestrator: create exe.dev integration + VM, provision via pyinfra."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time

from devbox import claude_auth, config, exe, paseo, provision

ACCOUNT_REQUIRED = ["exe_vm_name", "ts_auth_key"]
# Hub is installed separately, so provision has no business interrogating the
# user for an owner login it will never pass to a deploy.
HUB_REQUIRED = ["exe_vm_name", "hub_owner_email", "hub_owner_password"]

TS_KEY_PREFIX = "tskey-"
# Sandbox microVM pool geometry. Not in ACCOUNT_REQUIRED: these have working
# defaults, so a missing value is filled in rather than prompted for.
AGENT_POOL_SIZE_DEFAULT = 2
AGENT_MEMORY_DEFAULT = 2048
# A sanity floor, not a measured minimum -- it exists to catch `--agent-memory 2`
# from someone thinking in GiB, which would otherwise produce a pool of machines
# too small to boot.
AGENT_MEMORY_MIN = 256
# Hub refuses to bootstrap below this, and the refusal surfaces as the unit
# timing out after 600s rather than as anything that names the password.
HUB_PASSWORD_MIN = 12

_USER_REPO_RE = re.compile(r"[A-Za-z0-9._-]+")


def validate_auth_key(key: str) -> str:
    if not key.startswith(TS_KEY_PREFIX):
        raise ValueError(
            f"expected a Tailscale auth key starting with {TS_KEY_PREFIX!r}"
        )
    return key


def validate_hub_password(password: str) -> str:
    if len(password) < HUB_PASSWORD_MIN:
        raise ValueError(
            f"Hub requires at least {HUB_PASSWORD_MIN} characters, "
            f"got {len(password)}"
        )
    return password


def validate_pool_size(value) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"expected a whole number of microVMs, got: {value!r}")
    if size < 1:
        raise ValueError(f"the pool needs at least one microVM, got {size}")
    return size


def validate_agent_memory(value) -> int:
    try:
        mib = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"expected a whole number of MiB, got: {value!r}")
    if mib < AGENT_MEMORY_MIN:
        raise ValueError(
            f"expected MiB per microVM, got {mib} — the minimum is "
            f"{AGENT_MEMORY_MIN} (did you mean {mib * 1024}?)"
        )
    return mib


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
    # Cached like --vm-name, so these are set once rather than on every run.
    prov.add_argument("--agent-pool-size", type=int,
                      help="sandbox microVMs to keep pooled "
                           f"(default {AGENT_POOL_SIZE_DEFAULT}); "
                           "one per concurrent sandboxed session")
    prov.add_argument("--agent-memory", type=int,
                      help="MiB of memory per sandbox microVM "
                           f"(default {AGENT_MEMORY_DEFAULT})")

    add = sub.add_parser("add-repo", help="enable a GitHub repo as a Paseo project")
    add.add_argument("repo_spec", help="GitHub repo as user/repo")

    hub = sub.add_parser("hub", help="manage the self-hosted Paseo Hub")
    hub_sub = hub.add_subparsers(dest="hub_command", required=True)
    for action, help_text in [
        ("install", "install Hub, Postgres and the webhook filter"),
        ("uninstall", "remove Hub and its containers, images and data"),
    ]:
        hub_action = hub_sub.add_parser(action, help=help_text)
        hub_action.add_argument(
            "--vm-name", help="exe.dev VM name (overrides the cached one)")

    return p.parse_args(argv)


def preflight(tools=("ssh", "claude")) -> list[str]:
    return [tool for tool in tools if shutil.which(tool) is None]


def is_secret_field(field: str) -> bool:
    return field.endswith(("secret", "password", "key"))


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

    `required` is narrowed by the subcommands that need less -- add-repo and
    hub uninstall want a VM name and nothing else, so neither should interrogate
    the user for credentials it will never pass to a deploy.
    """
    acct = config.load_toml(config.ACCOUNT_PATH)
    # merge skips None/"", so an omitted flag keeps the cached value.
    merged = config.merge(acct, overrides or {})
    for field in config.missing_fields(merged, required or ACCOUNT_REQUIRED):
        merged[field] = _prompt(field, secret=is_secret_field(field))
    if merged != acct:
        config.save_toml(config.ACCOUNT_PATH, merged)
    return merged


# Trust first-seen host keys, matching the connector setting in
# deploy/inventory.py. Without this an unknown fingerprint fails every probe --
# BatchMode can't prompt to accept it -- so the wait below burns its whole
# timeout on a VM that is actually up. accept-new still refuses a *changed*
# key, which is what you want if a VM was recreated under the same name.
SSH_TRUST_OPTS = ["-o", "StrictHostKeyChecking=accept-new"]


def build_ssh_probe_args(host: str) -> list[str]:
    return ["ssh", *SSH_TRUST_OPTS,
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            host, "true"]


def _ssh_ready(host: str) -> tuple[bool, str]:
    result = subprocess.run(build_ssh_probe_args(host),
                            capture_output=True, text=True)
    return result.returncode == 0, result.stderr.strip()


def _wait_for_ssh(host: str, timeout=300) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        ready, last_error = _ssh_ready(host)
        if ready:
            return
        time.sleep(5)
    # Report why, so a changed host key or a refused connection is obvious
    # rather than looking like a slow boot.
    raise TimeoutError(
        f"SSH to {host} not ready within {timeout}s: {last_error or 'no error output'}"
    )


def _cmd_provision(ns) -> int:
    missing = preflight()
    if missing:
        print(f"Missing required tools on PATH: {', '.join(missing)}",
              file=sys.stderr)
        return 1

    account = _resolve_account_config(overrides={
        "exe_vm_name": ns.vm_name,
        "agent_pool_size": ns.agent_pool_size,
        "agent_memory": ns.agent_memory,
    })

    # Fail here rather than half-way through the deploy on the VM.
    try:
        ts_key = validate_auth_key(account["ts_auth_key"])
        # Absent until someone passes the flag, so default rather than prompt.
        pool_size = validate_pool_size(
            account.get("agent_pool_size", AGENT_POOL_SIZE_DEFAULT))
        agent_memory = validate_agent_memory(
            account.get("agent_memory", AGENT_MEMORY_DEFAULT))
    except ValueError as err:
        print(f"{err}", file=sys.stderr)
        return 1

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

    # Provision via pyinfra (secrets via env). The deploy only runs
    # `tailscale up` when the node isn't already joined, so a one-time key is
    # never spent twice.
    print("Provisioning via pyinfra...")
    env = provision.build_env(dict(os.environ), host=host, ts_key=ts_key,
                              claude_token=token, agent_pool_size=pool_size,
                              agent_memory=agent_memory)
    provision.run_pyinfra(env)

    print(f"Done. Provisioned {host}.")
    print(f"Sandbox pool: {pool_size} microVM(s) at {agent_memory} MiB each.")
    print("Paseo daemon (6767) is on the tailnet — see the README to pair.")
    print("Hub is not installed: run `devbox.py hub install` if you want it.")
    return 0


def _hub_target(ns, required) -> tuple[dict, str]:
    """Resolve the account config and the VM host both hub commands deploy to."""
    account = _resolve_account_config(required=required,
                                      overrides={"exe_vm_name": ns.vm_name})
    return account, exe.vm_host(account["exe_vm_name"])


def _cmd_hub_install(ns) -> int:
    missing = preflight(("ssh",))
    if missing:
        print(f"Missing required tools on PATH: {', '.join(missing)}",
              file=sys.stderr)
        return 1

    account, host = _hub_target(ns, HUB_REQUIRED)

    # Fail here rather than 600s into a unit that will never come up.
    try:
        password = validate_hub_password(account["hub_owner_password"])
    except ValueError as err:
        print(f"hub_owner_password: {err}", file=sys.stderr)
        return 1

    print(f"Installing Paseo Hub on {host}...")
    env = provision.build_hub_env(dict(os.environ), host=host,
                                  owner_email=account["hub_owner_email"],
                                  owner_password=password)
    provision.run_pyinfra(env, deploy=provision.HUB_INSTALL)

    print("Done. Hub is on the tailnet at port 3000 — see the README to pair.")
    return 0


def _cmd_hub_uninstall(ns) -> int:
    missing = preflight(("ssh",))
    if missing:
        print(f"Missing required tools on PATH: {', '.join(missing)}",
              file=sys.stderr)
        return 1

    _, host = _hub_target(ns, ["exe_vm_name"])

    print(f"Removing Paseo Hub from {host}...")
    # No credentials: a teardown has no use for them.
    env = provision.build_hub_env(dict(os.environ), host=host)
    provision.run_pyinfra(env, deploy=provision.HUB_UNINSTALL)

    print("Done. Hub, its containers, images and database are gone.")
    return 0


HUB_COMMANDS = {"install": _cmd_hub_install, "uninstall": _cmd_hub_uninstall}


def _cmd_hub(ns) -> int:
    return HUB_COMMANDS[ns.hub_command](ns)


def _cmd_add_repo(ns) -> int:
    missing = preflight(("ssh",))
    if missing:
        print(f"Missing required tools on PATH: {', '.join(missing)}",
              file=sys.stderr)
        return 1

    try:
        user, repo = split_repo(ns.repo_spec)
    except ValueError as err:
        print(f"{err}", file=sys.stderr)
        return 1

    account = _resolve_account_config(required=["exe_vm_name"])
    vm_name = account["exe_vm_name"]
    host = exe.vm_host(vm_name)

    # exe.dev integration (create-if-missing), attached to the one VM.
    name = exe.integration_name(user, repo)
    if not exe.integration_exists(exe.list_integrations(), name):
        print(f"Creating GitHub integration {name} attached to vm:{vm_name}...")
        exe.add_integration(user, repo, vm_name)

    print(f"Registering {user}/{repo} as a Paseo workspace on {host}...")
    result = subprocess.run(
        ["ssh", *SSH_TRUST_OPTS, host, paseo.build_clone_cmd(user, repo)])
    if result.returncode != 0:
        return result.returncode

    print(f"Done. {user}/{repo} is available in Paseo under {paseo.CLONE_DIR}.")
    return 0


COMMANDS = {
    "provision": _cmd_provision,
    "add-repo": _cmd_add_repo,
    "hub": _cmd_hub,
}


def main(argv=None) -> int:
    ns = parse_args(sys.argv[1:] if argv is None else argv)
    # Explicit, so a subcommand added without a handler fails loudly rather
    # than silently provisioning the box.
    try:
        return COMMANDS[ns.command](ns)
    except exe.ExeError as err:
        # exe.dev refusing a name or a duplicate is a user-facing condition, not
        # a bug in devbox -- report it rather than dumping a traceback.
        print(f"{err}", file=sys.stderr)
        return 1
