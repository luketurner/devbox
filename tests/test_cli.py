import pytest

from devbox import cli, exe


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


def test_validate_auth_key_accepts_a_tailscale_key():
    assert cli.validate_auth_key("tskey-auth-abc123") == "tskey-auth-abc123"


def test_validate_auth_key_rejects_anything_else():
    # An OAuth client secret pasted by mistake, for instance.
    with pytest.raises(ValueError):
        cli.validate_auth_key("tskey")
    with pytest.raises(ValueError):
        cli.validate_auth_key("")


def test_hub_password_meets_hub_bootstrap_minimum():
    assert cli.validate_hub_password("a" * 12) == "a" * 12


def test_hub_password_rejects_anything_shorter():
    # Hub refuses to bootstrap below 12 and says so only by timing out after
    # 600s, so catch it before the deploy starts.
    with pytest.raises(ValueError):
        cli.validate_hub_password("a" * 11)
    with pytest.raises(ValueError):
        cli.validate_hub_password("")


def test_pool_size_accepts_whole_numbers_from_flag_or_cached_config():
    # argparse gives an int; local/config.toml can hand back either.
    assert cli.validate_pool_size(3) == 3
    assert cli.validate_pool_size("3") == 3
    assert cli.validate_pool_size(1) == 1


def test_pool_size_rejects_an_empty_pool():
    # Zero machines means every sandboxed session is refused, which would look
    # like the provider being broken rather than a config choice.
    for bad in (0, -1, "nonsense", None):
        with pytest.raises(ValueError):
            cli.validate_pool_size(bad)


def test_agent_memory_accepts_mib():
    assert cli.validate_agent_memory("4096") == 4096
    assert cli.validate_agent_memory(cli.AGENT_MEMORY_MIN) == cli.AGENT_MEMORY_MIN


def test_agent_memory_catches_gib_mistaken_for_mib():
    # `--agent-memory 2` meaning 2 GiB would otherwise build a pool of machines
    # too small to boot, and say nothing about why.
    with pytest.raises(ValueError) as err:
        cli.validate_agent_memory(2)
    assert "2048" in str(err.value)


def test_agent_memory_rejects_nonsense():
    for bad in (0, -1, "lots", None):
        with pytest.raises(ValueError):
            cli.validate_agent_memory(bad)


def test_pool_geometry_has_defaults_rather_than_prompts():
    # These have working defaults, so provision must not interrogate the user
    # for them the way it does for a Tailscale key.
    assert "agent_pool_size" not in cli.ACCOUNT_REQUIRED
    assert "agent_memory" not in cli.ACCOUNT_REQUIRED
    assert cli.validate_pool_size(cli.AGENT_POOL_SIZE_DEFAULT) >= 1
    assert cli.validate_agent_memory(cli.AGENT_MEMORY_DEFAULT) == 2048


def test_auth_key_prompt_is_masked():
    # Every credential in ACCOUNT_REQUIRED must be prompted for as a secret.
    assert cli.is_secret_field("ts_auth_key") is True
    assert cli.is_secret_field("hub_owner_password") is True
    assert cli.is_secret_field("exe_vm_name") is False
    assert cli.is_secret_field("hub_owner_email") is False


def test_ssh_probe_trusts_first_seen_host_keys():
    args = cli.build_ssh_probe_args("vm.exe.xyz")
    assert args[0] == "ssh"
    assert args[-2:] == ["vm.exe.xyz", "true"]
    assert "BatchMode=yes" in args
    # Without this an unknown fingerprint fails every probe -- BatchMode can't
    # prompt -- and _wait_for_ssh burns its whole timeout on a healthy VM.
    assert "StrictHostKeyChecking=accept-new" in args


def test_parse_args_provision():
    ns = cli.parse_args(["provision"])
    assert ns.command == "provision"
    assert ns.vm_name is None


def test_parse_args_provision_vm_name():
    ns = cli.parse_args(["provision", "--vm-name", "devbox"])
    assert ns.vm_name == "devbox"


def test_parse_args_provision_pool_geometry():
    ns = cli.parse_args(["provision", "--agent-pool-size", "3",
                         "--agent-memory", "4096"])
    assert (ns.agent_pool_size, ns.agent_memory) == (3, 4096)


def test_parse_args_provision_pool_geometry_is_optional():
    # Omitted flags must stay None so config.merge keeps the cached value
    # rather than overwriting it with a default.
    ns = cli.parse_args(["provision"])
    assert ns.agent_pool_size is None
    assert ns.agent_memory is None


def test_parse_args_hub_install():
    ns = cli.parse_args(["hub", "install"])
    assert (ns.command, ns.hub_command) == ("hub", "install")
    assert ns.vm_name is None


def test_parse_args_hub_uninstall():
    ns = cli.parse_args(["hub", "uninstall"])
    assert (ns.command, ns.hub_command) == ("hub", "uninstall")


def test_parse_args_hub_takes_vm_name_like_provision():
    for action in ("install", "uninstall"):
        ns = cli.parse_args(["hub", action, "--vm-name", "devbox"])
        assert ns.vm_name == "devbox"


def test_parse_args_hub_requires_an_action():
    # A bare `hub` must not be ambiguous about install vs uninstall.
    with pytest.raises(SystemExit):
        cli.parse_args(["hub"])


def test_every_subcommand_has_a_handler():
    # main() dispatches through these dicts; a missing entry would be a
    # KeyError at run time rather than at import.
    assert set(cli.COMMANDS) == {"provision", "add-repo", "hub"}
    assert set(cli.HUB_COMMANDS) == {"install", "uninstall"}


def test_main_reports_exe_errors_instead_of_raising(monkeypatch, capsys):
    # An exe.dev refusal (a rejected name, an existing VM) is a user-facing
    # condition; unhandled it reached the user as a two-level traceback.
    def boom(ns):
        raise exe.ExeError('invalid name: name must be lowercase')

    monkeypatch.setitem(cli.COMMANDS, "provision", boom)
    assert cli.main(["provision"]) == 1
    assert "must be lowercase" in capsys.readouterr().err


def test_provision_no_longer_requires_hub_credentials():
    # Hub is installed by its own command, so provision must not prompt for an
    # owner login it will never pass to a deploy.
    assert "hub_owner_email" not in cli.ACCOUNT_REQUIRED
    assert "hub_owner_password" not in cli.ACCOUNT_REQUIRED
    assert cli.ACCOUNT_REQUIRED == ["exe_vm_name", "ts_auth_key"]


def test_hub_install_requires_the_owner_credentials():
    assert set(cli.HUB_REQUIRED) == {
        "exe_vm_name", "hub_owner_email", "hub_owner_password"}


def test_parse_args_add_repo():
    ns = cli.parse_args(["add-repo", "me/widgets"])
    assert ns.command == "add-repo"
    assert ns.repo_spec == "me/widgets"


def test_parse_args_requires_a_subcommand():
    with pytest.raises(SystemExit):
        cli.parse_args([])


def test_preflight_tools_are_selectable():
    # add-repo has no reason to require a local claude.
    assert cli.preflight(("definitely-not-a-real-binary",)) == [
        "definitely-not-a-real-binary"
    ]
    assert cli.preflight(("ssh",)) == []
