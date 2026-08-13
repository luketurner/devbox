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


def test_parse_items_bare_list():
    assert exe.parse_items('[{"name": "a"}]', ["machines"]) == [{"name": "a"}]


def test_parse_items_wrapped():
    raw = '{"machines": [{"name": "a"}, {"name": "b"}]}'
    assert exe.parse_items(raw, ["machines", "vms"]) == [
        {"name": "a"}, {"name": "b"},
    ]


def test_exists_predicates():
    items = [{"name": "me-repo"}, {"name": "other"}]
    assert exe.integration_exists(items, "me-repo") is True
    assert exe.vm_exists(items, "missing") is False
