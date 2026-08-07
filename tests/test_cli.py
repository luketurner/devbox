import pytest

from devbox import cli


def test_split_repo():
    assert cli.split_repo("me/widgets") == ("me", "widgets")


def test_split_repo_rejects_bad_input():
    with pytest.raises(ValueError):
        cli.split_repo("noslash")


def test_parse_args_prefix_optional():
    ns = cli.parse_args(["me/widgets", "--prefix", "acme"])
    assert ns.repo_spec == "me/widgets"
    assert ns.prefix == "acme"
