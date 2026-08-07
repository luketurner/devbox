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
    # Streams output to the user's terminal in real time (so the login
    # URL/instructions are visible) while also capturing it to extract the
    # token.
    proc = subprocess.Popen(
        ["claude", "setup-token"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    captured = []
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")           # stream to the user so the browser/login prompt is visible
        captured.append(line)
    code = proc.wait()
    if code != 0:
        raise subprocess.CalledProcessError(code, ["claude", "setup-token"])
    return extract_token("".join(captured))


def ensure_token(cached: str | None, *, runner=_run_setup_token) -> str:
    if cached:
        return cached
    return runner()
