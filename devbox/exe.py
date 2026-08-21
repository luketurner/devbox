"""Thin wrappers over the `ssh exe.dev ...` CLI."""
from __future__ import annotations

import json
import subprocess


def vm_host(name: str) -> str:
    return f"{name}.exe.xyz"


def integration_name(user: str, repo: str) -> str:
    # Owner-qualified: one VM now serves many repos, and bare repo names
    # collide across owners. Lowercased because exe.dev refuses anything else
    # ("invalid name: name must be lowercase"), and GitHub owners and repos
    # routinely have capitals.
    return f"{user}-{repo}".lower()


def build_integration_add_args(user: str, repo: str, vm_name: str) -> list[str]:
    return [
        "integrations", "add", "github",
        "--name", integration_name(user, repo),
        # As typed, unlike --name: GitHub matches owner/repo case-insensitively,
        # and this URL's last segment is what names the clone directory.
        "--repository", f"{user}/{repo}",
        # Attach to the VM directly. The old tag:<repo> form paired with a
        # matching tag on the VM, which is what made this one-VM-per-repo.
        "--attach", f"vm:{vm_name}",
    ]


def build_new_vm_args(name: str, tags: list[str]) -> list[str]:
    args = ["new", "--name", name]
    for tag in tags:
        args += ["--tag", tag]
    args.append("--json")
    return args


def parse_items(raw: str, keys: list[str]) -> list[dict]:
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    for key in keys:
        if key in data:
            value = data[key]
            return value if isinstance(value, list) else []
    # Returning [] here would read as "nothing exists", which is the opposite
    # of "I couldn't understand this" -- and it made provision try to create a
    # VM that was already there. Fail loudly instead.
    raise ValueError(
        f"unrecognised exe.dev JSON: expected a list or one of {keys}, "
        f"got keys {sorted(data)}"
    )


def _has_value(items: list[dict], field: str, value: str) -> bool:
    return any(item.get(field) == value for item in items)


def integration_exists(items: list[dict], name: str) -> bool:
    return _has_value(items, "name", name)


def vm_exists(items: list[dict], name: str) -> bool:
    # `ls --json` calls it vm_name; only integrations use plain `name`.
    return _has_value(items, "vm_name", name)


class ExeError(RuntimeError):
    """An `ssh exe.dev ...` command failed, with whatever it said on stderr."""


def run_exe(args, *, input=None, capture=True):
    try:
        return subprocess.run(
            ["ssh", "exe.dev", *args],
            input=input,
            capture_output=capture,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as err:
        # capture_output swallows stderr, so a bare CalledProcessError says only
        # "returned non-zero exit status 1" and hides what exe.dev actually
        # reported. Surface it.
        detail = ((err.stderr or "") + (err.stdout or "")).strip()
        raise ExeError(
            f"exe.dev {' '.join(args)} failed (exit {err.returncode})"
            + (f": {detail}" if detail else "")
        ) from err


def list_integrations() -> list[dict]:
    out = run_exe(["integrations", "list", "--json"]).stdout
    return parse_items(out, ["integrations"])


def add_integration(user: str, repo: str, vm_name: str) -> None:
    run_exe(build_integration_add_args(user, repo, vm_name))


def list_vms() -> list[dict]:
    out = run_exe(["ls", "--json"]).stdout
    return parse_items(out, ["vms"])


def create_vm(name: str, tags: list[str]) -> None:
    run_exe(build_new_vm_args(name, tags))
