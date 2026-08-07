from devbox import claude_auth


def test_extract_token():
    out = "Paste this token into CI:\n  sk-ant-oat01-ABCdef123  \nDone.\n"
    assert claude_auth.extract_token(out) == "sk-ant-oat01-ABCdef123"


def test_ensure_token_returns_cached():
    called = False

    def runner():
        nonlocal called
        called = True
        return "unused"

    assert claude_auth.ensure_token("sk-ant-cached", runner=runner) == "sk-ant-cached"
    assert called is False


def test_ensure_token_runs_when_missing():
    assert claude_auth.ensure_token(None, runner=lambda: "sk-ant-new") == "sk-ant-new"
    assert claude_auth.ensure_token("", runner=lambda: "sk-ant-new") == "sk-ant-new"
