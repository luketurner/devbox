from devbox import exe


def test_vm_host():
    assert exe.vm_host("acme", "widgets") == "acme-widgets.exe.xyz"


def test_build_integration_add_args():
    args = exe.build_integration_add_args("me", "repo")
    assert args == [
        "integrations", "add", "github",
        "--name", "repo",
        "--repository", "me/repo",
        "--attach", "tag:repo",
    ]


def test_build_new_vm_args():
    args = exe.build_new_vm_args("acme-repo", ["dev", "repo"])
    assert args == [
        "new", "--name", "acme-repo",
        "--tag", "dev", "--tag", "repo", "--json",
    ]


def test_parse_items_bare_list():
    assert exe.parse_items('[{"name": "a"}]', ["machines"]) == [{"name": "a"}]


def test_parse_items_wrapped():
    raw = '{"machines": [{"name": "a"}, {"name": "b"}]}'
    assert exe.parse_items(raw, ["machines", "vms"]) == [
        {"name": "a"}, {"name": "b"},
    ]


def test_exists_predicates():
    items = [{"name": "repo"}, {"name": "other"}]
    assert exe.integration_exists(items, "repo") is True
    assert exe.vm_exists(items, "missing") is False
