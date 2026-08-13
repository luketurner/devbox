import pytest

from devbox import cli


def test_split_repo():
    assert cli.split_repo("me/widgets") == ("me", "widgets")


def test_split_repo_rejects_bad_input():
    with pytest.raises(ValueError):
        cli.split_repo("noslash")


def test_split_repo_rejects_multiple_slashes():
    with pytest.raises(ValueError):
        cli.split_repo("a/b/c")


def test_split_repo_rejects_invalid_chars():
    with pytest.raises(ValueError):
        cli.split_repo("me/bad;rm")


def test_split_repo_allows_valid_charset():
    assert cli.split_repo("me/my-repo.js_v2") == ("me", "my-repo.js_v2")


def test_parse_args_provision():
    ns = cli.parse_args(["provision"])
    assert ns.command == "provision"
    assert ns.vm_name is None


def test_parse_args_provision_vm_name():
    ns = cli.parse_args(["provision", "--vm-name", "devbox"])
    assert ns.vm_name == "devbox"


def test_parse_args_add_repo():
    ns = cli.parse_args(["add-repo", "me/widgets"])
    assert ns.command == "add-repo"
    assert ns.repo_spec == "me/widgets"


def test_parse_args_requires_a_subcommand():
    with pytest.raises(SystemExit):
        cli.parse_args([])


def test_preflight_tools_are_selectable():
    # add-repo has no reason to require a local claude.
    assert cli.preflight(("definitely-not-a-real-binary",)) == [
        "definitely-not-a-real-binary"
    ]
    assert cli.preflight(("ssh",)) == []
