"""DESIGN-20261114（Deepin P0）host-grant web 审批链路测试.

覆盖验收矩阵的 web 侧：
- host_grant 类审批仅接受有效浏览器登录会话（web_session 通道）——
  未登录 loopback → 403 human_auth_required（loopback 不能自批）；
  Bearer API 通道 → 403；记录保持 pending
- 登录会话批准 → 持久 grant 签发（data/grants）+ 记录 host_grant_id +
  escalation_review_log 审计；grant 带 request_binding/policy_hash
- 决定冲突（expected_sha256 失配）→ 孤儿 grant 被撤销（审计）
- denied → 不签发 grant
- 灾难命令类审批 loopback 语义不变（回归保护，P0 不收紧该类）
- loopback 显式登录：表单带密码+已配置 → Set-Cookie；JSON 带密码 → 400；
  JSON 无密码 → auth_required=False（零回归）；未配置密码 → 503 引导
- list/detail 透传 request_kind/host_request，永不投影 token
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_loop.tools.builtin.host_access import HostAccessRequestTool
from llm_loop.tools.escalation import (
    EscalationStore,
    HostCapabilityGrantStore,
)
from llm_loop.web import build_app
from llm_loop.web.auth import SESSION_COOKIE_NAME

_API_KEY = "test-web-api-key-host-grant"
_REVIEW = "/api/v1/escalation/review"
_LOGIN = "/auth/login"


@pytest.fixture
def store(isolated_data_dir):
    return EscalationStore(isolated_data_dir / "audit" / "escalation_requests.json")


@pytest.fixture
def gstore(isolated_data_dir):
    # P0-1（2026-11-14）: home 经 LFL_HOST_GRANT_HOME（conftest 注入
    # tmp/host-grants）推导，fail-closed 校验通过后构造 store。
    return HostCapabilityGrantStore(Path(os.environ["LFL_HOST_GRANT_HOME"]).resolve())


@pytest.fixture
def host_pending(store, tmp_path):
    """由 host_access_request 工具创建的 host_grant 申请（冻结字段服务端生成）."""
    from llm_loop.core.run_context import current_session_id, current_workspace_root

    tok = current_session_id.set("host-web-sess")
    wtok = current_workspace_root.set(str(tmp_path))
    try:
        f = (tmp_path / "secret-note.txt").resolve()
        f.write_text("top", encoding="utf-8")
        res = HostAccessRequestTool(store).execute(
            path=str(f), operation="write", command=f"tee {f}",
            justification="web 审批链路单元测试必要性说明",
        )
    finally:
        current_session_id.reset(tok)
        current_workspace_root.reset(wtok)
    assert res.status.name == "SUCCESS", res.content
    rid = res.content.split("request_id=")[1].splitlines()[0].strip()
    return rid, f


def _expected_sha(store, rid: str) -> str:
    return str(store.get(rid)["command_sha256"])


def _client(build_test_engine, monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_API_KEY", _API_KEY)
    monkeypatch.delenv("WEB_LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("WEB_ORIGIN_ALLOWLIST", raising=False)
    engine, _fake = build_test_engine([{"content": "ok"}])
    return TestClient(build_app(engine=engine))


def _login_session(client: TestClient) -> None:
    token = client.app.state.web_sessions.create(ttl_seconds=3600)
    client.cookies.set(SESSION_COOKIE_NAME, token)


def _grant_files(isolated_data_dir):
    # P0-1（2026-11-14）: 账本已与 LFL_DATA_DIR 分离——经同源推导取 home。
    d = Path(os.environ["LFL_HOST_GRANT_HOME"]).resolve() / "grants"
    return list(d.glob("*.json")) if d.exists() else []


# ── 1. loopback 未登录不能自批 ────────────────────────────

def test_loopback_unauthenticated_cannot_approve_host_grant(
    store, host_pending, build_test_engine, isolated_data_dir, monkeypatch
):
    """无鉴权要求（loopback）+ 无会话 cookie → 403 human_auth_required."""
    for var in ("WEB_AUTH_REQUIRE", "WEB_API_KEY", "WEB_LOGIN_PASSWORD_HASH", "WEB_ORIGIN_ALLOWLIST"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    engine, _f = build_test_engine([{"content": "ok"}])
    loop = TestClient(build_app(engine=engine), base_url="http://127.0.0.1", client=("127.0.0.1", 51423))
    rid, _f_path = host_pending
    r = loop.post(
        _REVIEW,
        json={"id": rid, "decision": "approved", "expected_sha256": _expected_sha(store, rid)},
    )
    assert r.status_code == 403
    body = r.json()
    assert body["error"] == "human_auth_required"
    assert store.get(rid)["status"] == "pending"
    assert _grant_files(isolated_data_dir) == []



def test_bearer_channel_cannot_approve_host_grant(
    store, host_pending, build_test_engine, monkeypatch
):
    for var in ("WEB_AUTH_REQUIRE", "WEB_API_KEY", "WEB_LOGIN_PASSWORD_HASH", "WEB_ORIGIN_ALLOWLIST"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("WEB_API_KEY", _API_KEY)
    engine, _f = build_test_engine([{"content": "ok"}])
    loop = TestClient(build_app(engine=engine), base_url="http://127.0.0.1", client=("127.0.0.1", 51423))
    rid, _fp = host_pending
    r = loop.post(
        _REVIEW,
        headers={"Authorization": f"Bearer {_API_KEY}"},
        json={"id": rid, "decision": "approved", "expected_sha256": _expected_sha(store, rid)},
    )
    assert r.status_code == 403
    assert r.json()["error"] in ("human_auth_required", "human_channel_required")
    assert store.get(rid)["status"] == "pending"



def test_logged_in_session_approval_issues_persistent_grant(
    store, gstore, host_pending, build_test_engine, monkeypatch, isolated_data_dir
):
    client = _client(build_test_engine, monkeypatch)
    _login_session(client)
    rid, f = host_pending
    r = client.post(
        _REVIEW,
        json={"id": rid, "decision": "approved", "expected_sha256": _expected_sha(store, rid)},
    )
    assert r.status_code == 200, r.text
    rec = store.get(rid)
    gid = rec["host_grant_id"]
    assert gid
    # 持久 grant 文件 + 绑定字段
    grant = gstore.peek(gid)
    assert grant["canonical_path"] == str(f)
    assert grant["operation"] == "write"
    assert grant["requester_session_id"] == "host-web-sess"
    assert grant["request_binding"]["request_id"] == rid
    assert grant["request_binding"]["file_sha256"] == hashlib.sha256(b"top").hexdigest()
    assert grant["policy_hash"]
    # 响应体不回 grant_id 之外的敏感面（token 恒空）
    assert "token" not in r.json()["request"]
    # 审计
    log = (isolated_data_dir / "audit" / "escalation_review_log.jsonl")
    assert log.exists() and rid in log.read_text(encoding="utf-8")


def test_denied_issues_no_grant(store, host_pending, build_test_engine, monkeypatch, isolated_data_dir):
    client = _client(build_test_engine, monkeypatch)
    _login_session(client)
    rid, _fp = host_pending
    r = client.post(
        _REVIEW,
        json={"id": rid, "decision": "denied", "expected_sha256": _expected_sha(store, rid)},
    )
    assert r.status_code == 200
    assert not store.get(rid).get("host_grant_id")
    assert _grant_files(isolated_data_dir) == []


def test_stale_review_revokes_orphan_grant(
    store, gstore, host_pending, build_test_engine, monkeypatch
):
    """expected_sha256 失配（409）后不得残留已签发 grant——孤儿撤销."""
    client = _client(build_test_engine, monkeypatch)
    _login_session(client)
    rid, _fp = host_pending
    r = client.post(
        _REVIEW,
        json={"id": rid, "decision": "approved", "expected_sha256": "0" * 64},
    )
    assert r.status_code in (409, 400)
    assert store.get(rid)["status"] == "pending"
    grants = gstore.list_all() if hasattr(gstore, "list_all") else []
    if not grants:
        # store 无 list_all：扫描目录（P0-1: home 为独立安全状态目录，
        # grant 文件在 home/grants/ 单层）
        d = Path(os.environ["LFL_HOST_GRANT_HOME"]).resolve() / "grants"
        grants = [gstore.peek(p.stem) for p in d.glob("*.json")] if d.exists() else []
    for g in grants:
        if g and g.get("status") == "approved" and g.get("request_binding", {}).get("request_id") == rid:
            pytest.fail(f"孤儿 grant 未被撤销: {g['grant_id']}")


# ── 3. 灾难命令类审批语义不变（回归） ─────────────────────

def test_catastrophic_class_loopback_semantics_unchanged(store, build_test_engine, monkeypatch):
    """普通 command 类审批在 loopback（无鉴权要求）下仍可 web:loopback 通过（既有行为）."""
    rec = store.create(
        tool_name="execute_command",
        command="cat /etc/hosts",
        justification="灾难类审批语义回归保护",
        session_id="s-x",
    )
    for var in ("WEB_AUTH_REQUIRE", "WEB_API_KEY", "WEB_LOGIN_PASSWORD_HASH", "WEB_ORIGIN_ALLOWLIST"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    engine, _f = build_test_engine([{"content": "ok"}])
    loop = TestClient(build_app(engine=engine), base_url="http://127.0.0.1", client=("127.0.0.1", 51423))
    r = loop.post(
        _REVIEW,
        json={"id": rec["id"], "decision": "approved",
              "expected_sha256": hashlib.sha256(b"cat /etc/hosts").hexdigest()},
    )
    assert r.status_code == 200, r.text
    assert store.get(rec["id"])["decided_by"] == "web:loopback"



def _pw_hash(monkeypatch):
    from llm_loop.web.auth import hash_login_password
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password("unit-pass-123"))


def test_loopback_form_login_with_password_sets_cookie(build_test_engine, monkeypatch):
    for var in ("WEB_AUTH_REQUIRE", "WEB_API_KEY", "WEB_ORIGIN_ALLOWLIST"):
        monkeypatch.delenv(var, raising=False)
    _pw_hash(monkeypatch)
    engine, _f = build_test_engine([{"content": "ok"}])
    loop = TestClient(build_app(engine=engine), base_url="http://127.0.0.1", client=("127.0.0.1", 51423))
    r = loop.post(_LOGIN, data={"password": "unit-pass-123"}, follow_redirects=False)
    assert r.status_code in (303, 200), r.text
    assert SESSION_COOKIE_NAME in r.headers.get("set-cookie", "")



def test_loopback_json_explicit_login_rejected(build_test_engine, monkeypatch):
    """AI/自动化 JSON 通道显式登录 → 400（防借登录通道为自批铺路）."""
    for var in ("WEB_AUTH_REQUIRE", "WEB_API_KEY", "WEB_ORIGIN_ALLOWLIST"):
        monkeypatch.delenv(var, raising=False)
    _pw_hash(monkeypatch)
    engine, _f = build_test_engine([{"content": "ok"}])
    loop = TestClient(build_app(engine=engine), base_url="http://127.0.0.1", client=("127.0.0.1", 51423))
    r = loop.post(_LOGIN, json={"password": "unit-pass-123"})
    assert r.status_code == 400
    assert r.json()["error"] == "explicit_login_browser_only"



def test_loopback_json_probe_zero_regression(build_test_engine, monkeypatch):
    for var in ("WEB_AUTH_REQUIRE", "WEB_API_KEY", "WEB_ORIGIN_ALLOWLIST"):
        monkeypatch.delenv(var, raising=False)
    engine, _f = build_test_engine([{"content": "ok"}])
    loop = TestClient(build_app(engine=engine), base_url="http://127.0.0.1", client=("127.0.0.1", 51423))
    r = loop.post(_LOGIN, json={})
    assert r.status_code == 200
    assert r.json()["auth_required"] is False



def test_loopback_form_login_without_config_fails_closed(build_test_engine, monkeypatch):
    for var in ("WEB_AUTH_REQUIRE", "WEB_API_KEY", "WEB_LOGIN_PASSWORD_HASH", "WEB_ORIGIN_ALLOWLIST"):
        monkeypatch.delenv(var, raising=False)
    engine, _f = build_test_engine([{"content": "ok"}])
    loop = TestClient(build_app(engine=engine), base_url="http://127.0.0.1", client=("127.0.0.1", 51423))
    r = loop.post(_LOGIN, data={"password": "whatever"})
    assert r.status_code == 503



def test_list_detail_expose_host_fields_without_token(store, host_pending, build_test_engine, monkeypatch):
    client = _client(build_test_engine, monkeypatch)
    _login_session(client)
    rid, _fp = host_pending
    lst = client.get("/api/v1/escalation/list").json()
    items = lst.get("items") or lst.get("requests") or []
    target = next((it for it in items if it.get("id") == rid), None)
    assert target is not None, lst
    assert target.get("request_kind") == "host_grant"
    assert "token" not in target
    det = client.get(f"/api/v1/escalation/detail?id={rid}").json()
    assert det.get("request_kind") == "host_grant"
    assert det.get("host_request", {}).get("host_operation") == "write"
    assert "token" not in det
