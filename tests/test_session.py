from devbox import session


def test_start_session_cmd_is_detached_and_named():
    cmd = session.build_start_session_cmd("myrepo")
    assert "herdr" in cmd
    assert "devbox" in cmd            # session name
    assert "myrepo" in cmd            # working dir
    assert "claude rc" in cmd
    assert "bypassPermissions" in cmd


def test_session_exists_cmd_names_session():
    assert "devbox" in session.session_exists_cmd("devbox")
