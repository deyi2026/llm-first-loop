"""HTTP 面：四头 HMAC 端到端、错误形状、产物授权、回执可见性。"""
from __future__ import annotations

import secrets
from datetime import timedelta

import pytest
from starlette.testclient import TestClient

from llm_loop.peer.admission import AdmissionStore
from llm_loop.peer.artifacts import ArtifactStore
from llm_loop.peer.auth import PeerAuthenticator, sign_request
from llm_loop.peer.models import GrantRecord, iso, now_local
from llm_loop.peer.service import PeerService
from llm_loop.peer.store import PeerStore
from llm_loop.web.peer_routes import create_peer_app

SECRET = b"\x09" * 32
NOW = 1_800_000_000


class Client:
    """带四头签名的测试客户端（每次请求新 nonce，可显式复用做重放测试）。"""

    def __init__(self, app, *, node_id="deepin-01", secret=SECRET, ts=NOW):
        self._c = TestClient(app)
        self.node_id = node_id
        self.secret = secret
        self.ts = ts

    def headers(self, method, path, *, query="", body=b"", nonce=None, secret=None, ts=None):
        return sign_request(
            secret=secret or self.secret,
            method=method,
            path=path,
            query=query,
            node_id=self.node_id,
            nonce=nonce or secrets.token_hex(16),
            timestamp=self.ts if ts is None else ts,
            body=body,
        )

    def get(self, path, *, query="", **kw):
        return self._c.get(path + (f"?{query}" if query else ""), headers=self.headers("GET", path, query=query, **kw))

    def post(self, path, payload, **kw):
        import json

        body = json.dumps(payload).encode()
        headers = self.headers("POST", path, body=body, **kw)
        headers["Content-Type"] = "application/json"
        return self._c.post(path, content=body, headers=headers)


@pytest.fixture()
def env(tmp_path):
    allowed = tmp_path / "work"
    allowed.mkdir()
    store = PeerStore(tmp_path / "peer")
    store.issue_grant(
        GrantRecord(
            grant_id="gr_ABCDEFGH1234",
            node_id="deepin-01",
            issued_by={"ingress": "feishu", "human": "lfl"},
            issued_at=iso(now_local()),
            expires_at=iso(now_local() + timedelta(hours=1)),
            state="active",
            allowed_kinds=("fs.read", "fs.list"),
            allowed_paths=(str(allowed),),
            max_concurrency=2,
            max_tasks_total=5,
        )
    )
    service = PeerService(
        store=store,
        admissions=AdmissionStore(tmp_path / "peer"),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        node_id="deepin-01",
    )
    authenticator = PeerAuthenticator(secret_for=lambda n: SECRET if n == "deepin-01" else None, clock=lambda: NOW)
    app = create_peer_app(service=service, authenticator=authenticator)
    return Client(app), allowed, store


def test_manifest_requires_headers(env):
    client, _allowed, _store = env
    res = client._c.get("/peer/v1/manifest")
    assert res.status_code == 401
    assert res.json()["reason_code"] == "peer_bad_signature"
    assert res.json()["suggested_next"]


def test_manifest_with_signature(env):
    client, _allowed, _store = env
    res = client.get("/peer/v1/manifest")
    assert res.status_code == 200
    body = res.json()
    assert body["node_id"] == "deepin-01" and body["grant"]["grant_id"] == "gr_ABCDEFGH1234"


def test_wrong_secret_and_unknown_node(env):
    client, _allowed, _store = env
    assert client.get("/peer/v1/manifest", secret=b"\x08" * 32).status_code == 401
    other = Client(client._c.app, node_id="deepin-99")
    res = other.get("/peer/v1/manifest")
    assert res.status_code == 401 and res.json()["reason_code"] == "peer_unknown_node"


def test_body_and_query_are_signed(env):
    client, allowed, _store = env
    (allowed / "a.txt").write_text("hello")
    payload = {
        "schema": "lfl.peer.v1",
        "effect_id": "eff_00000001",
        "kind": "fs.read",
        "params": {"path": str(allowed / "a.txt")},
        "deadline_s": 30,
    }
    import json

    body = json.dumps(payload).encode()
    headers = client.headers("POST", "/peer/v1/tasks", body=body)
    tampered = client._c.post("/peer/v1/tasks", content=body.replace(b"eff_00000001", b"eff_00000002"), headers=headers)
    assert tampered.status_code == 401
    assert tampered.json()["reason_code"] == "peer_bad_signature"


def test_replay_is_rejected(env):
    client, _allowed, _store = env
    nonce = "a" * 32
    headers = client.headers("GET", "/peer/v1/manifest", nonce=nonce)
    assert client._c.get("/peer/v1/manifest", headers=headers).status_code == 200
    replay = client._c.get("/peer/v1/manifest", headers=headers)
    assert replay.status_code == 401 and replay.json()["reason_code"] == "peer_replay_detected"


def test_stale_timestamp_rejected(env):
    client, _allowed, _store = env
    headers = client.headers("GET", "/peer/v1/manifest", ts=NOW - 400)
    res = client._c.get("/peer/v1/manifest", headers=headers)
    assert res.status_code == 401 and res.json()["reason_code"] == "peer_stale_signature"


def test_submit_then_fetch_receipt_and_artifact(env):
    client, allowed, _store = env
    (allowed / "a.txt").write_text("hello")
    res = client.post(
        "/peer/v1/tasks",
        {
            "schema": "lfl.peer.v1",
            "effect_id": "eff_00000001",
            "kind": "fs.read",
            "params": {"path": str(allowed / "a.txt")},
            "deadline_s": 30,
            "expect": ["summary", "artifact"],
        },
    )
    assert res.status_code == 200, res.text
    receipt = res.json()
    assert receipt["state"] == "succeeded"

    again = client.get(f"/peer/v1/tasks/{receipt['task_id']}/receipt")
    assert again.status_code == 200 and again.json()["task_id"] == receipt["task_id"]

    ref = receipt["result"]["artifacts"][0]["ref"]
    path = "/peer/v1/artifacts/" + ref.removeprefix("artifact://")
    got = client.get(path)
    assert got.status_code == 200 and got.content == b"hello"


def test_artifact_of_another_node_is_invisible(env):
    client, allowed, store = env
    (allowed / "a.txt").write_text("hello")
    receipt = client.post(
        "/peer/v1/tasks",
        {
            "schema": "lfl.peer.v1",
            "effect_id": "eff_00000001",
            "kind": "fs.read",
            "params": {"path": str(allowed / "a.txt")},
            "deadline_s": 30,
        },
    ).json()
    ref = receipt["result"]["artifacts"][0]["ref"]
    path = "/peer/v1/artifacts/" + ref.removeprefix("artifact://")
    # 同 secret 但声明的 node_id 不同 → 认证阶段就未知节点
    other = Client(client._c.app, node_id="node-other")
    assert other.get(path).status_code == 401


def test_unknown_task_id_404(env):
    client, _allowed, _store = env
    res = client.get("/peer/v1/tasks/task_doesnotexist/receipt")
    assert res.status_code == 404
    assert res.json()["reason_code"] == "params_schema_invalid"


def test_invalid_json_body_is_400_class_error(env):
    client, _allowed, _store = env
    body = b"{not json"
    headers = client.headers("POST", "/peer/v1/tasks", body=body)
    res = client._c.post("/peer/v1/tasks", content=body, headers=headers)
    assert res.status_code == 400
    assert res.json()["reason_code"] == "params_schema_invalid"
