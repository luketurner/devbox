"""The sandbox microVM pool geometry.

paseo-agent-build sources pool.env as shell; paseo-agent-vm parses the same file
in Python. They previously kept private copies of these numbers under a "must
match" comment, and the point of the shared file is that they cannot drift --
so the thing worth testing is that both readers agree on what it says. A
disagreement would not fail loudly: the build would stock machines the wrapper
never claims, and sessions would be refused with the pool sitting idle.
"""
import importlib.machinery
import importlib.util
import pathlib
import re
import subprocess

import pytest

_FILES = pathlib.Path(__file__).resolve().parents[1] / "deploy" / "files"
_WRAPPER = _FILES / "paseo-agent-vm"
_TEMPLATE = _FILES / "paseo-agent-pool.env.j2"
_BUILD = _FILES / "paseo-agent-build"


def _load():
    spec = importlib.util.spec_from_loader(
        "paseo_agent_vm",
        importlib.machinery.SourceFileLoader("paseo_agent_vm", str(_WRAPPER)),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper = _load()


def _render(pool_size, memory):
    """Render the deploy template the way files.template would."""
    text = _TEMPLATE.read_text()
    text = text.replace("{{ agent_pool_size }}", str(pool_size))
    text = text.replace("{{ agent_memory }}", str(memory))
    assert "{{" not in text, "template has a placeholder the deploy doesn't fill"
    return text


def _shell_reads(path):
    """What paseo-agent-build sees when it sources the file."""
    out = subprocess.run(
        ["sh", "-c", f'. "{path}"; echo "$POOL_SIZE|$CPUS|$MEM"'],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    pool_size, cpus, mem = out.split("|")
    return {"POOL_SIZE": pool_size, "CPUS": cpus, "MEM": mem}


@pytest.mark.parametrize("pool_size,memory", [(1, 256), (2, 2048), (4, 8192)])
def test_shell_and_python_read_the_same_values(tmp_path, pool_size, memory):
    conf = tmp_path / "pool.env"
    conf.write_text(_render(pool_size, memory))

    from_shell = _shell_reads(conf)
    from_python = wrapper.read_pool_conf(str(conf))

    assert from_shell["POOL_SIZE"] == from_python["POOL_SIZE"] == str(pool_size)
    assert from_shell["MEM"] == from_python["MEM"] == str(memory)
    assert from_shell["CPUS"] == from_python["CPUS"]


def test_pool_names_match_what_the_build_script_creates(tmp_path):
    # The build script names machines paseo-agent-$i counting from 1; the
    # wrapper claims by the same names, so an off-by-one here is a pool the
    # wrapper can never claim from.
    conf = tmp_path / "pool.env"
    conf.write_text(_render(3, 2048))
    size = int(wrapper.read_pool_conf(str(conf))["POOL_SIZE"])
    assert [f"paseo-agent-{i}" for i in range(1, size + 1)] == [
        "paseo-agent-1", "paseo-agent-2", "paseo-agent-3"]


def test_missing_config_falls_back_rather_than_killing_every_session(tmp_path):
    # A half-finished provision should not take the provider down with it.
    values = wrapper.read_pool_conf(str(tmp_path / "absent.env"))
    assert values == wrapper.POOL_DEFAULTS
    assert int(values["POOL_SIZE"]) >= 1


def test_defaults_match_the_shipped_template(tmp_path):
    # The fallback is only reachable when pool.env is missing, so it has to
    # agree with what the deploy normally writes -- otherwise a broken provision
    # silently changes the pool geometry instead of preserving it.
    from devbox import cli
    conf = tmp_path / "pool.env"
    conf.write_text(_render(cli.AGENT_POOL_SIZE_DEFAULT, cli.AGENT_MEMORY_DEFAULT))
    assert wrapper.read_pool_conf(str(conf)) == wrapper.POOL_DEFAULTS


def test_build_script_hashes_the_pool_config():
    # Without this, shrinking the pool or changing --mem leaves the existing
    # machines in place and the build prints "unchanged".
    hash_line = next(line for line in _BUILD.read_text().splitlines()
                     if line.startswith("HASH="))
    assert "$POOL_CONF" in hash_line


def test_build_script_derives_names_from_pool_size():
    # A hard-coded POOL list would ignore --agent-pool-size entirely.
    body = _BUILD.read_text()
    assert re.search(r'POOL="\$POOL paseo-agent-\$i"', body)
    assert 'POOL="paseo-agent-1 paseo-agent-2"' not in body
