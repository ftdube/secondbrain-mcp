import asyncio
import json
import time

import jwt as pyjwt
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import server


def _keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _token(private_key, **claims):
    now = int(time.time())
    payload = {
        "iss": server.DEX_ISSUER,
        "aud": server.MCP_CLIENT_ID,
        "iat": now,
        "exp": now + 300,
        **claims,
    }
    return pyjwt.encode(payload, private_key, algorithm="RS256")


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(self._key)


async def _protected(_request):
    return PlainTextResponse("ok")


def _build_app():
    # A minimal app wrapping the real BearerAuthMiddleware — deliberately
    # not server.app, which also drags in the MCP mount, FTS5 index, and
    # vault watcher lifespan. This isolates exactly what's under test.
    app = Starlette(routes=[
        Route("/protected", _protected),
        Route("/health", _protected),  # exact path already in server.AUTH_PUBLIC
    ])
    app.add_middleware(server.BearerAuthMiddleware)
    return app


# BRD: FR-AUTH-1, NFR-AUTH-5
def test_missing_authorization_header_401():
    client = TestClient(_build_app())
    resp = client.get("/protected")
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}


# BRD: FR-AUTH-4
def test_missing_authorization_header_includes_www_authenticate():
    client = TestClient(_build_app())
    resp = client.get("/protected")
    www_auth = resp.headers["www-authenticate"]
    assert f'realm="{server.MCP_BASE_URL}"' in www_auth
    assert "resource_metadata=" in www_auth
    assert "/.well-known/oauth-protected-resource" in www_auth


# BRD: FR-AUTH-2
def test_public_path_bypasses_auth():
    client = TestClient(_build_app())
    resp = client.get("/health")
    assert resp.status_code == 200


# BRD: FR-AUTH-2
def test_extra_public_path_via_allowlist(monkeypatch):
    monkeypatch.setattr(server, "AUTH_PUBLIC", server.AUTH_PUBLIC | {"/protected"})
    client = TestClient(_build_app())
    resp = client.get("/protected")
    assert resp.status_code == 200


# BRD: FR-AUTH-3
def test_valid_token_allows_request(monkeypatch):
    private_key, public_key = _keypair()
    monkeypatch.setattr(server, "_get_jwks", lambda: _FakeJWKClient(public_key))
    token = _token(private_key)
    client = TestClient(_build_app())
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.text == "ok"


# BRD: FR-AUTH-3, FR-AUTH-5
def test_wrong_signature_401(monkeypatch):
    _unused_key, public_key = _keypair()
    other_private_key, _other_public = _keypair()
    monkeypatch.setattr(server, "_get_jwks", lambda: _FakeJWKClient(public_key))
    token = _token(other_private_key)  # signed with a key that does NOT match public_key
    client = TestClient(_build_app())
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json() == {"error": "invalid token"}


# BRD: FR-AUTH-3, FR-AUTH-5
def test_wrong_audience_401(monkeypatch):
    private_key, public_key = _keypair()
    monkeypatch.setattr(server, "_get_jwks", lambda: _FakeJWKClient(public_key))
    token = _token(private_key, aud="someone-else")
    client = TestClient(_build_app())
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# BRD: FR-AUTH-3, FR-AUTH-5
def test_wrong_issuer_401(monkeypatch):
    private_key, public_key = _keypair()
    monkeypatch.setattr(server, "_get_jwks", lambda: _FakeJWKClient(public_key))
    token = _token(private_key, iss="https://not-dex.example.com")
    client = TestClient(_build_app())
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# BRD: FR-AUTH-3, FR-AUTH-5
def test_expired_token_401(monkeypatch):
    private_key, public_key = _keypair()
    monkeypatch.setattr(server, "_get_jwks", lambda: _FakeJWKClient(public_key))
    token = _token(private_key, exp=int(time.time()) - 60)
    client = TestClient(_build_app())
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# BRD: NFR-AUTH-6
def test_missing_bearer_prefix_logs_truncated_header(caplog):
    long_header = "Basic " + "x" * 100
    client = TestClient(_build_app())
    with caplog.at_level("WARNING"):
        client.get("/protected", headers={"Authorization": long_header})
    messages = [r.getMessage() for r in caplog.records]
    assert any(long_header[:30] in m and long_header not in m for m in messages)


# BRD: FR-AUTH-6
def test_oauth_protected_resource_metadata():
    result = asyncio.run(server._oauth_metadata(None))
    body = json.loads(result.body)
    assert body == {
        "resource": server.MCP_BASE_URL,
        "authorization_servers": [server.DEX_ISSUER],
        "bearer_methods_supported": ["header"],
    }


# BRD: OI-5 (pins the exact MCP transport mount path, which is fastmcp-version-dependent — see agents.md)
def test_mcp_asgi_mounted_at_expected_path():
    paths = [route.path for route in server.mcp_asgi.routes]
    assert "/mcp" in paths
