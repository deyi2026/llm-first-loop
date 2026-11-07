"""控制端四工具 + PeerClient/PeerDirectory（DESIGN-20261107 §5.8.5/§D14）。

测法：starlette ``TestClient`` 扮演远端受控端，monkeypatch ``httpx.request`` 把
客户端**真实签名**的请求送进同一条路由栈——签名、nonce 重放、effect_id 幂等、
产物 digest 全部走真实代码，只替换传输层（不 mock 协议层）。

覆盖点：
- base_url 必须是纯 origin；effect_id 确定性且 run 作用域；
- 目录解析：未知节点/未配对分明；
- 四工具：peer_list 的 kinds 事实、peer_dispatch 白名单前置校验 + 幂等、
  peer_task 取回执、peer_fetch 的 inbox 落盘与写侧授权拒绝；
- 挂载：``_mount_peer_routes`` 后无签名请求 401（路由确实在主 app 上）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from llm_loop.core.run_context import current_write_scope
from llm_loop.core.write_scope import WriteScope
from llm_loop.peer.admission import AdmissionStore
from llm_loop.peer.artifacts import ArtifactStore
from llm_loop.peer.auth import PeerAuthenticator
from llm_loop.peer.client import (
    PeerClient,
    PeerDirectory,
    PeerEndpoint,
    effect_id_for,
    origin_of,
)
from llm_loop.peer.errors import PeerError
from llm_loop.peer.models import GrantRecord, NodeRecord, iso, now_local
from llm_loop.peer.pair import secret_key_from_store
from llm_loop.peer.service import PeerService
from llm_loop.peer.store import PeerStore
from llm_loop.tools.builtin.peer_tools import build_peer_tools
from llm_loop.web import _mount_peer_routes
from llm_loop.web.peer_routes import build_peer_router, install_peer_error_handler

SECRET = b"\x09" * 32
PEER_NODE = "deepin-01"
LOCAL_NODE = "lfl-mac"
KINDS = ("fs.read", "fs.list")


def _grant(allowed: str) -> GrantRecord:
    return GrantRecord(
        grant_id="gr_CLIENTTEST01",
        node_id=PEER_NODE,
        issued_by={"ingress": "feishu", "human": "lfl"},
        issued_at=iso(now_local()),
        expires_at=iso(now_local() + timedelta(hours=1)),
        state="active",
        allowed_kinds=KINDS,
        allowed_paths=(allowed,),
        max_concurrency=2,
        max_tasks_total=20,
    )


@pytest.fixture()
def world(tmp_path, monkeypatch):
    allowed = tmp_path / "work"
    allowed.mkdir()
    target = allowed / "a.txt"
    target.write_text("hello peer channel")

    # 受控端（远端）store 与 secret：secret_for 与真实装配一致，读自己的 secrets/<node>.key
    server_root = tmp_path / "peer_server"
    server_store = PeerStore(server_root)
    server_store.write_secret(LOCAL_NODE, SECRET.hex())
    server_store.issue_grant(_grant(str(allowed)))
    service = PeerService(
        store=server_store,
        admissions=AdmissionStore(server_root),
        artifacts=ArtifactStore(server_root / "artifacts"),
        node_id=PEER_NODE,
        enabled_kinds=set(KINDS),
    )
    authenticator = PeerAuthenticator(
        secret_for=lambda n: (
            secret_key_from_store(server_store.read_secret(n))
            if server_store.read_secret(n)
            else None
        )
    )
    app = FastAPI()
    install_peer_error_handler(app)
    app.include_router(build_peer_router(service=service, authenticator=authenticator))

    test_client = TestClient(app, base_url="https://testserver")

    def _fake_request(method, url, *, headers=None, content=None, timeout=None, follow_redirects=False):
        return test_client.request(method, url, headers=headers, content=content)

    monkeypatch.setattr(httpx, "request", _fake_request)

    # 控制端（本机）store：nodes.json 记录对端 + 同一 shared secret
    client_root = tmp_path / "peer_client"
    client_store = PeerStore(client_root)
    client_store.upsert_node(
        NodeRecord(
            node_id=PEER_NODE,
            display_name="deepin lab",
            role="worker",
            base_url="https://testserver",
            display_protocol="none",
            state="paired",
            paired_at=iso(now_local()),
        )
    )
    client_store.write_secret(PEER_NODE, SECRET.hex())

    settings = SimpleNamespace(
        peer_enabled=True,
        peer_node_id=LOCAL_NODE,
        peer_display_name="",
        peer_data_dir=str(client_root),
        peer_timeout_s=10,
        data_dir=str(tmp_path / "data"),
        _extra={"runtime_root": str(allowed)},
    )
    return SimpleNamespace(
        allowed=allowed,
        target=target,
        client_store=client_store,
        directory=PeerDirectory(client_store, local_node_id=LOCAL_NODE),
        tools=build_peer_tools(settings),
        app=app,
        test_client=test_client,
        settings=settings,
    )


def test_origin_requires_bare_origin():
    assert origin_of("http://127.0.0.1:8787/") == "http://127.0.0.1:8787"
    with pytest.raises(PeerError) as excinfo:
        origin_of("http://127.0.0.1:8787/peer")
    assert excinfo.value.reason_code == "peer_transport_unavailable"


def test_effect_id_is_deterministic_and_run_scoped():
    first = effect_id_for(run_key="s1:1", peer_id="p", kind="fs.read", params={"path": "/a"})
    same = effect_id_for(run_key="s1:1", peer_id="p", kind="fs.read", params={"path": "/a"})
    other_run = effect_id_for(run_key="s1:2", peer_id="p", kind="fs.read", params={"path": "/a"})
    other_kind = effect_id_for(run_key="s1:1", peer_id="p", kind="fs.list", params={"path": "/a"})
    assert first == same and len(first) == 44
    assert first != other_run and first != other_kind


def test_directory_resolve_matches_store_state(world):
    client = world.directory.resolve(PEER_NODE)
    assert client.node_id == PEER_NODE
    with pytest.raises(PeerError) as excinfo:
        world.directory.resolve("definitely-unknown")
    assert excinfo.value.reason_code == "peer_unknown_node"
    world.client_store.set_node_state(PEER_NODE, "revoked")
    with pytest.raises(PeerError) as excinfo:
        world.directory.resolve(PEER_NODE)
    assert excinfo.value.reason_code == "peer_not_paired"


def test_peer_client_signs_manifest(world):
    body = world.directory.resolve(PEER_NODE).manifest()
    assert body["node_id"] == PEER_NODE
    assert [item["kind"] for item in body["kinds"]] == list(KINDS)


def test_peer_client_maps_wrong_secret_to_reason_code(world):
    bad = PeerClient(
        PeerEndpoint(node_id=PEER_NODE, base_url="https://testserver", secret=b"\x08" * 32),
        local_node_id=LOCAL_NODE,
    )
    with pytest.raises(PeerError) as excinfo:
        bad.manifest()
    assert excinfo.value.reason_code == "peer_bad_signature"


def test_peer_list_reports_kinds_and_health(world):
    result = world.tools["peer_list"].execute()
    assert result.status == "success", result.content
    payload = json.loads(result.content)
    assert payload["local_node_id"] == LOCAL_NODE
    row = payload["peers"][0]
    assert row["peer_id"] == PEER_NODE and row["health"] == "ok"
    assert [item["kind"] for item in row["kinds"]] == list(KINDS)


def test_peer_dispatch_is_idempotent(world):
    args = {
        "peer_id": PEER_NODE,
        "kind": "fs.read",
        "params": {"path": str(world.target)},
        "expect": ["summary", "artifact"],
    }
    first = json.loads(world.tools["peer_dispatch"].execute(**args).content)
    second = json.loads(world.tools["peer_dispatch"].execute(**args).content)
    assert first["effect_id"] == second["effect_id"]
    assert first["receipt"]["task_id"] == second["receipt"]["task_id"]
    assert first["receipt"]["state"] == "succeeded"


def test_peer_dispatch_rejects_kind_outside_whitelist(world):
    result = world.tools["peer_dispatch"].execute(
        peer_id=PEER_NODE, kind="exec", params={"cmd": "id"}
    )
    assert result.status == "failure"
    assert result.content.startswith("[policy_task_kind_not_allowed]")


def test_peer_task_returns_receipt(world):
    dispatched = json.loads(
        world.tools["peer_dispatch"]
        .execute(peer_id=PEER_NODE, kind="fs.read", params={"path": str(world.target)})
        .content
    )
    task_id = dispatched["receipt"]["task_id"]
    result = world.tools["peer_task"].execute(peer_id=PEER_NODE, task_id=task_id)
    assert result.status == "success", result.content
    receipt = json.loads(result.content)["receipt"]
    assert receipt["task_id"] == task_id


def test_peer_fetch_writes_inbox_and_verifies_digest(world):
    receipt = json.loads(
        world.tools["peer_dispatch"]
        .execute(
            peer_id=PEER_NODE,
            kind="fs.read",
            params={"path": str(world.target)},
            expect=["summary", "artifact"],
        )
        .content
    )["receipt"]
    ref = receipt["result"]["artifacts"][0]["ref"]
    result = world.tools["peer_fetch"].execute(peer_id=PEER_NODE, ref=ref)
    assert result.status == "success", result.content
    payload = json.loads(result.content)
    assert payload["sha256"] == hashlib.sha256(world.target.read_bytes()).hexdigest()
    written = world.settings.peer_data_dir + "/inbox/" + payload["sha256"]
    assert payload["local_path"] == written
    with open(payload["local_path"], "rb") as handle:
        assert handle.read() == world.target.read_bytes()


def test_peer_fetch_to_path_outside_scope_is_rejected(world):
    receipt = json.loads(
        world.tools["peer_dispatch"]
        .execute(
            peer_id=PEER_NODE,
            kind="fs.read",
            params={"path": str(world.target)},
            expect=["artifact"],
        )
        .content
    )["receipt"]
    ref = receipt["result"]["artifacts"][0]["ref"]
    token = current_write_scope.set(
        WriteScope(paths=("outbox/",), mode="allow", declared=True)
    )
    try:
        result = world.tools["peer_fetch"].execute(
            peer_id=PEER_NODE, ref=ref, to_path=str(world.allowed / "a.txt")
        )
    finally:
        current_write_scope.reset(token)
    assert result.status == "failure"
    assert result.content.startswith("[path_outside_allowed_paths]")


def test_mount_peer_routes_requires_signature(world):
    app = FastAPI()
    _mount_peer_routes(app, world.settings)
    anonymous = TestClient(app)
    response = anonymous.get("/peer/v1/manifest")
    assert response.status_code == 401
    assert response.json()["reason_code"] == "peer_bad_signature"


def test_origin_of_enforces_d15_plaintext_loopback_only():
    """独立审查 P1-1（2026-11-08）：明文 http 仅允许 loopback；非 loopback 必须 https。"""
    from llm_loop.peer.client import origin_of

    assert origin_of("http://127.0.0.1:8903") == "http://127.0.0.1:8903"
    assert origin_of("http://localhost") == "http://localhost"
    assert origin_of("http://[::1]:8903") == "http://[::1]:8903"
    assert origin_of("https://203.0.113.20:8903") == "https://203.0.113.20:8903"
    with pytest.raises(PeerError) as lan_plain:
        origin_of("http://203.0.113.20:8903")
    assert lan_plain.value.reason_code == "peer_transport_unavailable"
    assert "D15" in str(lan_plain.value)
