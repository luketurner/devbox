"""pyinfra inventory: single exe.dev host, data pulled from the environment."""
import os

_host = os.environ["DEVBOX_HOST"]

hosts = [
    (
        _host,
        {
            "ts_authkey": os.environ["DEVBOX_TS_AUTHKEY"],
            "claude_token": os.environ["CLAUDE_CODE_OAUTH_TOKEN"],
            "hub_owner_email": os.environ["DEVBOX_HUB_OWNER_EMAIL"],
            "hub_owner_password": os.environ["DEVBOX_HUB_OWNER_PASSWORD"],
            # Let paramiko use the user's ssh config and trust first-seen keys,
            # matching the manual `ssh <name>.exe.xyz` flow.
            "ssh_strict_host_key_checking": "accept-new",
        },
    )
]
