"""Mint ephemeral Tailscale auth keys via OAuth client credentials."""
from __future__ import annotations

import httpx

TS_API = "https://api.tailscale.com"


def build_key_request(tag: str) -> dict:
    return {
        "capabilities": {
            "devices": {
                "create": {
                    "reusable": False,
                    "ephemeral": True,
                    "preauthorized": True,
                    "tags": [tag],
                }
            }
        },
        "expirySeconds": 3600,
    }


def parse_key_response(data: dict) -> str:
    return data["key"]


def get_access_token(client_id: str, client_secret: str, *,
                     client: httpx.Client) -> str:
    resp = client.post(
        "/api/v2/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def mint_key(tailnet: str, tag: str, client_id: str, client_secret: str, *,
             client: httpx.Client) -> str:
    token = get_access_token(client_id, client_secret, client=client)
    resp = client.post(
        f"/api/v2/tailnet/{tailnet}/keys",
        headers={"Authorization": f"Bearer {token}"},
        json=build_key_request(tag),
    )
    resp.raise_for_status()
    return parse_key_response(resp.json())
