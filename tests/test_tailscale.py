import httpx

from devbox import tailscale


def test_build_key_request():
    body = tailscale.build_key_request("tag:devbox")
    caps = body["capabilities"]["devices"]["create"]
    assert caps["ephemeral"] is True
    assert caps["preauthorized"] is True
    assert caps["reusable"] is False
    assert caps["tags"] == ["tag:devbox"]


def test_parse_key_response():
    assert tailscale.parse_key_response({"key": "tskey-abc"}) == "tskey-abc"


def test_mint_key_flow():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/oauth/token":
            return httpx.Response(200, json={"access_token": "at-123"})
        assert request.headers["Authorization"] == "Bearer at-123"
        assert request.url.path == "/api/v2/tailnet/example.com/keys"
        return httpx.Response(200, json={"key": "tskey-xyz"})

    client = httpx.Client(transport=httpx.MockTransport(handler),
                          base_url=tailscale.TS_API)
    key = tailscale.mint_key("example.com", "tag:devbox", "cid", "csecret",
                             client=client)
    assert key == "tskey-xyz"
