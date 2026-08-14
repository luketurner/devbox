import pytest

from devbox import exe


def test_vm_host():
    assert exe.vm_host("devbox") == "devbox.exe.xyz"


def test_integration_name_is_owner_qualified():
    assert exe.integration_name("me", "repo") == "me-repo"


def test_build_integration_add_args_attaches_to_the_vm():
    args = exe.build_integration_add_args("me", "repo", "devbox")
    assert args == [
        "integrations", "add", "github",
        "--name", "me-repo",
        "--repository", "me/repo",
        "--attach", "vm:devbox",
    ]


def test_build_new_vm_args():
    args = exe.build_new_vm_args("devbox", ["dev"])
    assert args == ["new", "--name", "devbox", "--tag", "dev", "--json"]


# Trimmed from real `ssh exe.dev ... --json` output. The shapes differ: `ls`
# wraps in {"vms": [...]} and names the field vm_name, while `integrations
# list` is a bare array using plain `name`. Assuming `name` for both is what
# made vm_exists always return False, so provision kept trying to recreate an
# existing VM.
LS_JSON = (
    '{"vms":[{"vm_name":"lt-devbox-paseo","status":"running","tags":["dev"],'
    '"ssh_host":"lt-devbox-paseo.exe.xyz"},'
    '{"vm_name":"lt-paseo","status":"running","tags":["dev","devbox"]}]}'
)
INTEGRATIONS_JSON = (
    '[{"attachments":["tag:devbox"],"config":{"repositories":["luketurner/devbox"]},'
    '"name":"devbox","type":"github"},'
    '{"attachments":["auto:all"],"name":"notify","type":"notify"}]'
)


def test_parse_items_bare_list():
    assert exe.parse_items('[{"name": "a"}]', ["vms"]) == [{"name": "a"}]


def test_vm_exists_against_real_ls_output():
    vms = exe.parse_items(LS_JSON, ["vms"])
    assert len(vms) == 2
    assert exe.vm_exists(vms, "lt-devbox-paseo") is True
    assert exe.vm_exists(vms, "lt-paseo") is True
    assert exe.vm_exists(vms, "never-created") is False


def test_integration_exists_against_real_list_output():
    items = exe.parse_items(INTEGRATIONS_JSON, ["integrations"])
    assert exe.integration_exists(items, "devbox") is True
    assert exe.integration_exists(items, "luketurner-devbox") is False


def test_parse_items_tolerates_an_empty_account():
    assert exe.parse_items('{"vms":[]}', ["vms"]) == []
    assert exe.parse_items('{"vms":null}', ["vms"]) == []


def test_parse_items_raises_on_an_unrecognised_shape():
    # Silently returning [] would read as "no VMs exist".
    with pytest.raises(ValueError):
        exe.parse_items('{"somethingelse": [{"vm_name": "x"}]}', ["vms"])


def test_run_exe_surfaces_stderr_on_failure(monkeypatch):
    import subprocess

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1, args[0], output="", stderr="vm lt-devbox-paseo already exists")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(exe.ExeError) as err:
        exe.run_exe(["new", "--name", "x"])
    # The bare CalledProcessError hid this, leaving only "exit status 1".
    assert "already exists" in str(err.value)
    assert "new --name x" in str(err.value)
