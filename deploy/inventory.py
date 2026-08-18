"""pyinfra inventory: single exe.dev host, data pulled from the environment."""
import os

_host = os.environ["DEVBOX_HOST"]

hosts = [
    (
        _host,
        {
            # Optional, unlike DEVBOX_HOST: provision and the two hub deploys
            # share this inventory but pass different subsets, so demanding
            # every one here would make `hub uninstall` need a Tailscale key.
            # Each deploy file asserts the values it actually uses.
            "ts_authkey": os.environ.get("DEVBOX_TS_AUTHKEY"),
            "claude_token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
            "hub_owner_email": os.environ.get("DEVBOX_HUB_OWNER_EMAIL"),
            "hub_owner_password": os.environ.get("DEVBOX_HUB_OWNER_PASSWORD"),
            "agent_pool_size": os.environ.get("DEVBOX_AGENT_POOL_SIZE"),
            "agent_memory": os.environ.get("DEVBOX_AGENT_MEMORY"),
            # Let paramiko use the user's ssh config and trust first-seen keys,
            # matching the manual `ssh <name>.exe.xyz` flow.
            "ssh_strict_host_key_checking": "accept-new",
            # The initial connect races VM boot and the exe.dev proxy.
            "ssh_connect_retries": 5,
        },
    )
]
