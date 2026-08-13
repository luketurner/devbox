from devbox import paseo


def test_repo_url_uses_the_exe_dev_integration():
    assert paseo.repo_url("me", "widgets") == (
        "https://github.int.exe.xyz/me/widgets.git"
    )


def test_build_clone_cmd():
    cmd = paseo.build_clone_cmd("me", "widgets")
    assert cmd == (
        "paseo clone --dir ~/projects "
        "https://github.int.exe.xyz/me/widgets.git"
    )


def test_build_clone_cmd_honours_dir():
    assert "--dir /srv/code " in paseo.build_clone_cmd("me", "w", dir="/srv/code")


def test_build_clone_cmd_leaves_tilde_for_the_remote_shell():
    # Quoting ~ would defeat expansion on the far side.
    assert "--dir ~/projects" in paseo.build_clone_cmd("me", "w")
