"""Register a GitHub repo as a Paseo workspace on the VM."""
from __future__ import annotations

import shlex

CLONE_DIR = "~/projects"
DAEMON_PORT = 6767


def repo_url(user: str, repo: str) -> str:
    # The exe.dev integration, not github.com: the VM has no GitHub credentials
    # of its own, and this URL is what the daemon and microVMs can reach.
    return f"https://github.int.exe.xyz/{user}/{repo}.git"


def build_clone_cmd(user: str, repo: str, dir: str = CLONE_DIR) -> str:
    # The daemon binds the tailnet IP only -- deliberately, since a microVM's
    # 127.0.0.1 is the host's loopback under smolvm's TSI backend, so listening
    # there would let a sandboxed agent drive the daemon. The CLI defaults to
    # localhost:6767 and gets ECONNREFUSED, so point it at the right address.
    #
    # Resolved on the VM at run time, like the daemon wrapper does, so it
    # survives the tailnet IP changing. Left unquoted (as is `dir`'s leading ~)
    # so the remote shell expands it.
    host = f'"$(tailscale ip -4 | head -n1):{DAEMON_PORT}"'
    return (f"paseo clone --dir {dir} --host {host} "
            f"{shlex.quote(repo_url(user, repo))}")
