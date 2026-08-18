from pathlib import Path

import pytest

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
    )
    assert env["PATH"] == "/usr/bin"
    assert env["DEVBOX_HOST"] == "devbox.exe.xyz"
    assert env["DEVBOX_TS_AUTHKEY"] == "tskey-abc"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-xyz"


def test_build_env_carries_no_hub_credentials():
    # Hub is a separate deploy now; provision has no reason to hold its login.
    env = provision.build_env({}, host="devbox.exe.xyz", ts_key="tskey-abc",
                              claude_token="sk-ant-xyz")
    assert "DEVBOX_HUB_OWNER_EMAIL" not in env
    assert "DEVBOX_HUB_OWNER_PASSWORD" not in env


def test_build_hub_env_sets_the_owner_login():
    env = provision.build_hub_env(
        {"PATH": "/usr/bin"},
        host="devbox.exe.xyz",
        owner_email="me@example.com",
        owner_password="hunter2hunter2",
    )
    assert env["PATH"] == "/usr/bin"
    assert env["DEVBOX_HOST"] == "devbox.exe.xyz"
    assert env["DEVBOX_HUB_OWNER_EMAIL"] == "me@example.com"
    assert env["DEVBOX_HUB_OWNER_PASSWORD"] == "hunter2hunter2"


def test_build_hub_env_omits_credentials_when_uninstalling():
    # A teardown has no use for them, so it should not be handed any.
    env = provision.build_hub_env({}, host="devbox.exe.xyz")
    assert env["DEVBOX_HOST"] == "devbox.exe.xyz"
    assert "DEVBOX_HUB_OWNER_EMAIL" not in env
    assert "DEVBOX_HUB_OWNER_PASSWORD" not in env


def test_deploy_paths_all_exist():
    # A typo in one of these would only surface once pyinfra was already
    # connected to the VM.
    root = Path(provision.__file__).resolve().parent.parent
    for path in (provision.INVENTORY, provision.DEPLOY,
                 provision.HUB_INSTALL, provision.HUB_UNINSTALL):
        assert (root / path).is_file(), path


def test_build_pyinfra_args_defaults_to_the_provision_deploy():
    assert provision.DEPLOY in provision.build_pyinfra_args()


def test_build_pyinfra_args_takes_the_hub_deploys():
    for deploy in (provision.HUB_INSTALL, provision.HUB_UNINSTALL):
        args = provision.build_pyinfra_args(deploy)
        assert args[:2] == ["pyinfra", "-y"]
        assert args[2:4] == [provision.INVENTORY, deploy]


def test_build_pyinfra_args_does_not_stop_for_confirmation():
    # pyinfra reads stdin at "Detected changes ... skip this step with -y",
    # so without this a non-TTY caller dies on EOFError -- three times over,
    # since run_pyinfra retries.
    assert "-y" in provision.build_pyinfra_args()


class _FakeResult:
    def __init__(self, returncode):
        self.returncode = returncode


def _recorder(codes):
    """Returns a runner yielding the given exit codes, and its call log."""
    calls = []

    def runner(args, env=None):
        calls.append(args)
        return _FakeResult(codes[len(calls) - 1])

    return runner, calls


def test_build_pyinfra_args_retries_failed_operations():
    args = provision.build_pyinfra_args()
    # A dropped channel shouldn't abandon the host on the first blip.
    assert "--retry" in args
    assert "--retry-delay" in args


def test_run_pyinfra_retries_the_whole_run_then_succeeds():
    runner, calls = _recorder([1, 0])
    provision.run_pyinfra({}, attempts=3, delay=0, runner=runner, sleep=lambda _: None)
    assert len(calls) == 2


def test_run_pyinfra_passes_the_deploy_through():
    runner, calls = _recorder([0])
    provision.run_pyinfra({}, deploy=provision.HUB_UNINSTALL, attempts=1,
                          delay=0, runner=runner, sleep=lambda _: None)
    assert provision.HUB_UNINSTALL in calls[0]
    assert provision.DEPLOY not in calls[0]


def test_run_pyinfra_does_not_retry_on_success():
    runner, calls = _recorder([0, 0])
    provision.run_pyinfra({}, attempts=3, delay=0, runner=runner, sleep=lambda _: None)
    assert len(calls) == 1


def test_run_pyinfra_gives_up_and_raises():
    import subprocess

    runner, calls = _recorder([1, 1, 1])
    with pytest.raises(subprocess.CalledProcessError):
        provision.run_pyinfra({}, attempts=3, delay=0, runner=runner, sleep=lambda _: None)
    assert len(calls) == 3
