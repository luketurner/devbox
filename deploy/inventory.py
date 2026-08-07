"""pyinfra inventory: single exe.dev host, data pulled from the environment."""
import os

_host = os.environ["DEVBOX_HOST"]

hosts = [
    (
        _host,
        {
            "ts_authkey": os.environ["DEVBOX_TS_AUTHKEY"],
            "claude_token": os.environ["CLAUDE_CODE_OAUTH_TOKEN"],
            "repo": os.environ["DEVBOX_REPO"],
            # Let paramiko use the user's ssh config and trust first-seen keys,
            # matching the manual `ssh <name>.exe.xyz` flow.
            "ssh_strict_host_key_checking": "accept-new",
        },
    )
]
