"""Obtain and cache a Claude Code OAuth token (local browser login, once)."""
from __future__ import annotations

import re
import subprocess

_TOKEN_RE = re.compile(r"sk-ant-[A-Za-z0-9\-_]+")


def extract_token(output: str) -> str:
    matches = _TOKEN_RE.findall(output)
    if not matches:
        raise ValueError("no sk-ant- token found in `claude setup-token` output")
    return matches[-1]


def _run_setup_token() -> str:
    # Inherits the terminal so the local browser OAuth loopback works.
    proc = subprocess.run(
        ["claude", "setup-token"],
        capture_output=True,
        text=True,
        check=True,
    )
    return extract_token(proc.stdout)


def ensure_token(cached: str | None, *, runner=_run_setup_token) -> str:
    if cached:
        return cached
    return runner()
