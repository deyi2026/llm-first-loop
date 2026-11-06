"""M1「提权审批可信可恢复」web 层红→绿测试（2026-11-06 设计书）.

对应问题：
- ESC-07 待审列表被最新 50 条历史挤出 → FR-07 pending 独立分页
- ESC-08 存储读取错误伪装 200 空列表 → FR-08 如实 503
- ESC-05 长命令截断后无完整审阅入口 → FR-05 完整材料详情
"""

from __future__ import annotations

import hashlib
import os

import pytest
from fastapi.testclient import TestClient

from llm_loop.tools.escalation import EscalationStore
from llm_loop.web import build_app
from llm_loop.web.auth import SESSION_COOKIE_NAME

_CMD = "bash -lc 'echo m1-web'"
_API_KEY = "test-web-api-key-esc-m1"
_LIST = "/api/v1/escalation/list"
_DETAIL = "/api/v1/escalation/detail"


@pytest.fixture
def store(isolated_data_dir):
    return EscalationStore(isolated_data_dir / "audit" / "escalation_requests.json")


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_API_KEY", _API_KEY)
    monkeypatch.delenv("WEB_LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("WEB_ORIGIN_ALLOWLIST", raising=False)


@pytest.fixture
def client(build_test_engine, auth_on):
    engine, _fake = build_test_engine([{"content": "ok"}])
    return TestClient(build_app(engine=engine))


def _login(client: TestClient) -> str:
    token = client.app.state.web_sessions.create(ttl_seconds=3600)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return token


def _mk_pending(store: EscalationStore, command: str) -> str:
    rec = store.create(
        tool_name="execute_command",
        command=command,
        justification="M1 web 层回归测试" * 3,
        session_id="esc-m1",
    )
    return rec["id"]


# ---------------------------------------------------------------- ESC-07 ----


def test_pending_not_squeezed_out_by_newer_terminal_records(client, store):
    """60 条新终态记录不得把更早的 pending 挤出待审可见范围。"""
    _login(client)
    target = _mk_pending(store, _CMD)
    for i in range(60):
        rid = _mk_pending(store, f"{_CMD} --case={i}")
        store.decide(rid, "denied")

    resp = client.get(f"{_LIST}?status=pending&limit=50")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()["requests"]]
    assert target in ids, "pending 过滤查询必须穿透最新 50 条窗口找到全部待审"


def test_pending_filter_returns_only_pending(client, store):
    _login(client)
    keep = _mk_pending(store, _CMD)
    gone = _mk_pending(store, f"{_CMD} --x")
    store.decide(gone, "denied")

    resp = client.get(f"{_LIST}?status=pending")
    ids = [r["id"] for r in resp.json()["requests"]]
    assert keep in ids and gone not in ids


# ---------------------------------------------------------------- ESC-08 ----


def test_corrupt_store_returns_503_not_empty_200(client, store, isolated_data_dir):
    _login(client)
    path = isolated_data_dir / "audit" / "escalation_requests.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{corrupt-json", encoding="utf-8")

    resp = client.get(_LIST)
    assert resp.status_code == 503, "存储损坏必须如实 503，不得伪装空列表"
    assert resp.json().get("error"), "错误响应必须带 error 字段"


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root 无视读权限位，chmod 000 不产生 PermissionError",
)
def test_unreadable_store_returns_503(client, store, isolated_data_dir):
    _login(client)
    path = isolated_data_dir / "audit" / "escalation_requests.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]", encoding="utf-8")
    path.chmod(0o000)

    try:
        resp = client.get(_LIST)
    finally:
        path.chmod(0o644)
    assert resp.status_code == 503, "权限错误必须如实 503"
    assert resp.json().get("error")


# ---------------------------------------------------------------- ESC-05 ----


def test_detail_returns_untruncated_command(client, store):
    _login(client)
    long_cmd = f"bash -lc 'echo {('payload-' * 600)}'"  # >2000 字符
    rid = _mk_pending(store, long_cmd)

    listed = client.get(f"{_LIST}?status=pending").json()["requests"]
    item = next(r for r in listed if r["id"] == rid)
    assert item.get("command_truncated") is True
    assert len(item["command"]) < len(long_cmd), "列表展示层保持截断"

    resp = client.get(f"{_DETAIL}?id={rid}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["command"] == long_cmd, "详情端点必须返回未截断完整命令"
    assert detail["command_sha256"] == hashlib.sha256(long_cmd.encode("utf-8")).hexdigest()


def test_detail_unknown_id_returns_404(client, store):
    _login(client)
    resp = client.get(f"{_DETAIL}?id=esc_nonexistent")
    assert resp.status_code == 404
