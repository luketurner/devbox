from devbox import provision


def test_args_carry_no_secrets():
    args = provision.build_pyinfra_args()
    assert args[0] == "pyinfra"
    joined = " ".join(args)
    assert "tskey" not in joined and "sk-ant" not in joined


def test_build_env_sets_secrets_in_env():
    env = provision.build_env(
        {"PATH": "/usr/bin"},
        host="devbox.exe.xyz",
        ts_key="tskey-abc",
        claude_token="sk-ant-xyz",
        hub_owner_email="me@example.com",
        hub_owner_password="hunter2hunter2",
    )
    assert env["PATH"] == "/usr/bin"
    assert env["DEVBOX_HOST"] == "devbox.exe.xyz"
    assert env["DEVBOX_TS_AUTHKEY"] == "tskey-abc"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-xyz"
    assert env["DEVBOX_HUB_OWNER_EMAIL"] == "me@example.com"
    assert env["DEVBOX_HUB_OWNER_PASSWORD"] == "hunter2hunter2"
