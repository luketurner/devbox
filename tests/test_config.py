from pathlib import Path

from devbox import config


def test_merge_later_layers_win():
    merged = config.merge({"a": 1, "b": 2}, {"b": 3})
    assert merged == {"a": 1, "b": 3}


def test_merge_ignores_empty_overrides():
    merged = config.merge({"a": "keep"}, {"a": None, "b": ""})
    assert merged["a"] == "keep"
    assert "b" not in merged


def test_missing_fields():
    assert config.missing_fields({"a": "x"}, ["a", "b"]) == ["b"]
    assert config.missing_fields({"a": "x", "b": "y"}, ["a", "b"]) == []


def test_toml_round_trip(tmp_path: Path):
    p = tmp_path / "sub" / "c.toml"
    config.save_toml(p, {"github_user": "me", "repo_name": "r"})
    assert config.load_toml(p) == {"github_user": "me", "repo_name": "r"}


def test_load_missing_returns_empty(tmp_path: Path):
    assert config.load_toml(tmp_path / "nope.toml") == {}


def test_repo_config_path():
    assert config.repo_config_path("myrepo") == Path(".devbox") / "myrepo.toml"
