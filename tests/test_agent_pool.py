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
_MEMCHECK = _FILES / "paseo-agent-memcheck"


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


def _meminfo(tmp_path, available_mib, total_mib=8192, omit_available=False):
    lines = [f"MemTotal:       {total_mib * 1024} kB"]
    if not omit_available:
        lines.append(f"MemAvailable:   {available_mib * 1024} kB")
    path = tmp_path / "meminfo"
    path.write_text("\n".join(lines) + "\n")
    return path


def _memcheck(tmp_path, pool_size, memory, **kw):
    return subprocess.run(
        ["sh", str(_MEMCHECK), str(pool_size), str(memory)],
        env={"PATH": "/usr/bin:/bin", "MEMINFO": str(_meminfo(tmp_path, **kw))},
        capture_output=True, text=True,
    )


def test_pool_that_fits_is_accepted(tmp_path):
    result = _memcheck(tmp_path, 2, 2048, available_mib=6000)
    assert result.returncode == 0


def test_pool_exactly_filling_available_memory_is_accepted(tmp_path):
    # The boundary belongs to "fits": 4096 of 4096 is not an overcommit.
    assert _memcheck(tmp_path, 2, 2048, available_mib=4096).returncode == 0


def test_pool_one_mib_over_is_refused(tmp_path):
    result = _memcheck(tmp_path, 2, 2048, available_mib=4095)
    assert result.returncode == 1
    assert "does not fit" in result.stderr


def test_refusal_reports_the_numbers_it_used(tmp_path):
    result = _memcheck(tmp_path, 8, 2048, available_mib=6000, total_mib=8192)
    assert "16384" in result.stderr   # requested
    assert "6000" in result.stderr    # available
    assert "8192" in result.stderr    # total


def test_refusal_suggests_a_pool_size_that_would_fit(tmp_path):
    result = _memcheck(tmp_path, 8, 2048, available_mib=6000)
    assert "--agent-pool-size 2" in result.stderr


def test_refusal_does_not_suggest_an_empty_pool(tmp_path):
    # 3000 MiB free cannot hold even one 4096 MiB machine, and
    # `--agent-pool-size 0` would be rejected by the CLI anyway.
    result = _memcheck(tmp_path, 2, 4096, available_mib=3000)
    assert result.returncode == 1
    assert "--agent-pool-size 0" not in result.stderr


def test_refusal_does_not_suggest_memory_below_the_cli_floor(tmp_path):
    # 400 MiB across 8 machines is 50 MiB each, under the 256 MiB floor.
    result = _memcheck(tmp_path, 8, 2048, available_mib=400)
    assert result.returncode == 1
    assert "--agent-memory 50" not in result.stderr
    assert "neither flag" in result.stderr


def test_unreadable_meminfo_fails_open(tmp_path):
    # A box whose meminfo cannot be parsed is broken in a way this check cannot
    # speak to; blocking the deploy on it would be worse than proceeding.
    result = _memcheck(tmp_path, 2, 2048, available_mib=0, omit_available=True)
    assert result.returncode == 0
    assert "skipping" in result.stderr


def test_missing_arguments_are_a_usage_error(tmp_path):
    result = subprocess.run(["sh", str(_MEMCHECK)], capture_output=True, text=True)
    assert result.returncode == 2


def test_deploy_checks_memory_before_writing_the_pool_config():
    # Order matters: a rejected geometry must not reach pool.env, or the wrapper
    # would read a POOL_SIZE whose machines were never built.
    body = (pathlib.Path(__file__).resolve().parents[1] / "deploy" / "deploy.py").read_text()
    assert body.index("Check the agent pool fits in memory") < body.index(
        "Install agent pool config")
