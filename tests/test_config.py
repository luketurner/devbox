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


def test_account_path_is_repo_local():
    assert config.ACCOUNT_PATH.name == "config.toml"
    assert config.ACCOUNT_PATH.parent.name == "local"
    # Anchored to the checkout: pyproject.toml sits alongside local/.
    assert (config.REPO_ROOT / "pyproject.toml").exists()
    assert config.ACCOUNT_PATH.parent.parent == config.REPO_ROOT


def test_toml_round_trip(tmp_path: Path):
    p = tmp_path / "sub" / "c.toml"
    config.save_toml(p, {"ts_tailnet": "me", "exe_vm_name": "r"})
    assert config.load_toml(p) == {"ts_tailnet": "me", "exe_vm_name": "r"}


def test_save_toml_restricts_permissions(tmp_path: Path):
    p = tmp_path / "sub" / "c.toml"
    config.save_toml(p, {"ts_tailnet": "me", "exe_vm_name": "r"})
    assert p.stat().st_mode & 0o777 == 0o600


def test_load_missing_returns_empty(tmp_path: Path):
    assert config.load_toml(tmp_path / "nope.toml") == {}

