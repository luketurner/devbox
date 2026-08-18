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
    config.save_toml(p, {"exe_vm_name": "devbox", "hub_owner_email": "me@example.com"})
    assert config.load_toml(p) == {"exe_vm_name": "devbox", "hub_owner_email": "me@example.com"}


def test_save_toml_restricts_permissions(tmp_path: Path):
    p = tmp_path / "sub" / "c.toml"
    config.save_toml(p, {"exe_vm_name": "devbox", "hub_owner_email": "me@example.com"})
    assert p.stat().st_mode & 0o777 == 0o600


def test_load_missing_returns_empty(tmp_path: Path):
    assert config.load_toml(tmp_path / "nope.toml") == {}



def test_ints_round_trip_as_numbers(tmp_path):
    # The agent pool geometry is numeric; quoting it would hand the next run a
    # string to re-coerce, and merge() treats the two as different values.
    path = tmp_path / "config.toml"
    config.save_toml(path, {"agent_pool_size": 3, "agent_memory": 4096})
    assert "agent_pool_size = 3" in path.read_text()
    assert config.load_toml(path) == {"agent_pool_size": 3, "agent_memory": 4096}


def test_bools_still_encode_as_bools(tmp_path):
    # bool is a subclass of int, so the int branch must not swallow it.
    path = tmp_path / "config.toml"
    config.save_toml(path, {"flag": True, "off": False})
    assert config.load_toml(path) == {"flag": True, "off": False}


def test_omitted_flag_keeps_the_cached_geometry():
    # argparse hands None for a flag the user left off.
    assert config.merge({"agent_pool_size": 3},
                        {"agent_pool_size": None}) == {"agent_pool_size": 3}
