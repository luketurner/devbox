"""Register a GitHub repo as a Paseo workspace on the VM."""
from __future__ import annotations

import shlex

CLONE_DIR = "~/projects"


def repo_url(user: str, repo: str) -> str:
    # The exe.dev integration, not github.com: the VM has no GitHub credentials
    # of its own, and this URL is what the daemon and microVMs can reach.
    return f"https://github.int.exe.xyz/{user}/{repo}.git"


def build_clone_cmd(user: str, repo: str, dir: str = CLONE_DIR) -> str:
    # `dir` is left unquoted so the remote shell expands a leading ~.
    return f"paseo clone --dir {dir} {shlex.quote(repo_url(user, repo))}"
