"""The agent microVM egress allowlist.

Worth testing despite being generated: it is an allowlist standing in for a
denylist, so an error does not fail loudly -- it just quietly lets an agent reach
the tailnet again.
"""
import importlib.machinery
import importlib.util
import ipaddress
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "deploy" / "files" / "paseo-agent-egress"


def _load():
    spec = importlib.util.spec_from_loader(
        "paseo_agent_egress",
        importlib.machinery.SourceFileLoader("paseo_agent_egress", str(_SRC)),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


egress = _load()


def _allowed(addr):
    nets = egress.allowed_v4()
    return any(ipaddress.ip_address(addr) in net for net in nets)


@pytest.mark.parametrize(
    "addr",
    [
        "1.1.1.1",              # public resolver
        "8.8.8.8",              # public resolver
        "140.82.121.4",         # github.com
        "100.96.0.1",           # the guest's gateway: the github proxy path
        "100.96.0.2",           # the guest itself
        "100.63.255.255",       # boundary: just below CGNAT
        "100.128.0.1",          # boundary: just above CGNAT
        "172.15.255.255",       # boundary: just below RFC1918 172.16/12
        "172.32.0.1",           # boundary: just above RFC1918 172.16/12
    ],
)
def test_public_internet_stays_reachable(addr):
    assert _allowed(addr), "%s should be reachable from an agent" % addr


@pytest.mark.parametrize(
    "addr",
    [
        "100.94.153.34",        # the devbox's own tailnet address
        "100.100.100.100",      # MagicDNS / tailscaled's unauthenticated web API
        "100.64.0.0",           # CGNAT lower bound
        "100.127.255.255",      # CGNAT upper bound
        "10.0.0.5",             # RFC1918
        "172.17.0.2",           # docker bridge
        "192.168.1.10",         # RFC1918
        "169.254.169.254",      # link-local
    ],
)
def test_tailnet_and_private_ranges_are_unreachable(addr):
    assert not _allowed(addr), "%s should be out of an agent's reach" % addr


def test_gateway_exception_is_only_the_nat_link():
    """The /30 carved back out of CGNAT must not extend past the guest's link."""
    assert _allowed("100.96.0.3")
    assert not _allowed("100.96.0.4")


def test_no_v6_is_allowed(capsys):
    """v6 is denied by omission, and that is deliberate -- do not "restore" it.

    Allowing 2000::/3 looked free, since smolvm has no v6 egress. It was not:
    the netstack terminates the connection to an allowed v6 destination locally
    before failing to forward it, so Happy Eyeballs sees a successful connect,
    commits to the dead path, and never falls back to the v4 address that works.
    Denying the family still excludes what the old entry was there to exclude,
    the tailnet ULA fd7a:115c:a1e0::/48 included.
    """
    egress.main()
    flags = capsys.readouterr().out.split()
    assert flags, "an empty allowlist would be applied as no restriction at all"
    assert all(f.startswith("--allow-cidr=") for f in flags)
    assert sum(":" in f for f in flags) == 0, "no v6 CIDR may be allowed"
