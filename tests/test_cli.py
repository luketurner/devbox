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


def test_parse_args_prefix_optional():
    ns = cli.parse_args(["me/widgets", "--prefix", "acme"])
    assert ns.repo_spec == "me/widgets"
    assert ns.prefix == "acme"
