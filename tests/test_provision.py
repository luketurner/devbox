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
        hub_owner_email="me@example.com",
        hub_owner_password="hunter2hunter2",
    )
    assert env["PATH"] == "/usr/bin"
    assert env["DEVBOX_HOST"] == "devbox.exe.xyz"
    assert env["DEVBOX_TS_AUTHKEY"] == "tskey-abc"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-xyz"
    assert env["DEVBOX_HUB_OWNER_EMAIL"] == "me@example.com"
    assert env["DEVBOX_HUB_OWNER_PASSWORD"] == "hunter2hunter2"


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
