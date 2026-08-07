"""Thin wrappers over the `ssh exe.dev ...` CLI."""
from __future__ import annotations

import json
import subprocess


def vm_host(prefix: str, repo: str) -> str:
    return f"{prefix}-{repo}.exe.xyz"


def build_integration_add_args(user: str, repo: str) -> list[str]:
    return [
        "integrations", "add", "github",
        "--name", repo,
        "--repository", f"{user}/{repo}",
        "--attach", f"tag:{repo}",
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
        if isinstance(data.get(key), list):
            return data[key]
    return []


def _has_name(items: list[dict], name: str) -> bool:
    return any(item.get("name") == name for item in items)


def integration_exists(items: list[dict], name: str) -> bool:
    return _has_name(items, name)


def vm_exists(items: list[dict], name: str) -> bool:
    return _has_name(items, name)


def run_exe(args, *, input=None, capture=True):
    return subprocess.run(
        ["ssh", "exe.dev", *args],
        input=input,
        capture_output=capture,
        text=True,
        check=True,
    )


def list_integrations() -> list[dict]:
    out = run_exe(["integrations", "list", "--json"]).stdout
    return parse_items(out, ["integrations"])


def add_integration(user: str, repo: str) -> None:
    run_exe(build_integration_add_args(user, repo))


def list_vms() -> list[dict]:
    out = run_exe(["ls", "--json"]).stdout
    return parse_items(out, ["machines", "vms"])


def create_vm(name: str, tags: list[str]) -> None:
    run_exe(build_new_vm_args(name, tags))
