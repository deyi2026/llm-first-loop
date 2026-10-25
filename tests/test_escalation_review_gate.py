"""P0-5（安全审查建议书 2026-10-25 S0-2）提权审批人工因子回归闸门.

覆盖:
- Bearer-only（AI 通道）审批 → 403 human_channel_required，记录仍 pending；
- 有效会话 cookie → 200，decided_by 服务端派生 web:session:<sha256 前 8 位>，
  不再是硬编码 web_panel；
- 客户端伪造 decided_by/reviewer → 忽略不采信，审计记 client_claimed_by；
- expected_sha256 失配 → 409 stale_review（记录仍 pending）；缺失 → 400；
- 正常批准 → 令牌可被 escalation_wait 取到；重复审批 → 409；
- list 响应永不泄露 token（键与值双重断言）+ 携带展示-审批绑定字段；
- 未启用鉴权的本机回环 → web:loopback（残余风险通道，如实标注）。

注: 测试命令字符串为无害假目标（store 层不做 guard 校验，不会执行）。
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from llm_loop.tools.builtin.escalation import EscalationWaitTool
from llm_loop.tools.escalation import EscalationStore
from llm_loop.web import build_app
from llm_loop.web.auth import SESSION_COOKIE_NAME

_CMD = "rm -rf /etc/esc-gate-unit-test"
_API_KEY = "test-web-api-key-esc-gate"
_REVIEW = "/api/v1/escalation/review"
_LIST = "/api/v1/escalation/list"


@pytest.fixture
def store(isolated_data_dir):
    """与 web 端点同源存储（LFL_DATA_DIR 由 conftest autouse 隔离到 tmp）."""
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


def _pending(store: EscalationStore, command: str = _CMD) -> tuple[str, str]:
    rec = store.create(
        tool_name="execute_command",
        command=command,
        justification="P0-5 人工因子闸门回归测试",
        session_id="esc-gate",
    )
    return rec["id"], hashlib.sha256(command.encode("utf-8")).hexdigest()


def _login(client: TestClient) -> str:
    """服务端会话存储直接签发（等价真实登录产物；不引密码登录路径）."""
    token = client.app.state.web_sessions.create(ttl_seconds=3600)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return token


def _review_lines(isolated_data_dir) -> list[dict]:
    f = isolated_data_dir / "audit" / "escalation_review_log.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── 1. AI 通道（Bearer-only）不得审批 ──


def test_bearer_only_channel_cannot_review_and_stays_pending(client, store, isolated_data_dir):
    rid, sha = _pending(store)
    r = client.post(
        _REVIEW,
        headers={"Authorization": f"Bearer {_API_KEY}"},
        json={"id": rid, "decision": "approved", "expected_sha256": sha},
    )
    assert r.status_code == 403, r.text
    assert r.json()["error"] == "human_channel_required"
    assert store.get(rid)["status"] == "pending"  # 决定未落盘
    # AI 通道尝试审批本身是安全事件，必须留审计痕
    hits = [line for line in _review_lines(isolated_data_dir) if line.get("outcome") == "rejected_human_channel_required"]
    assert hits and hits[-1]["channel"] == "bearer_api_key" and hits[-1]["id"] == rid
    assert hits[-1]["remote_addr"]  # 来源地址入审计


# ── 2. 会话 cookie：服务端派生身份 ──


def test_session_cookie_review_200_with_derived_identity(client, store, isolated_data_dir):
    rid, sha = _pending(store)
    token = _login(client)
    r = client.post(
        _REVIEW, json={"id": rid, "decision": "approved", "expected_sha256": sha, "note": "人工批准"}
    )
    assert r.status_code == 200, r.text
    rec = r.json()["request"]
    expect = "web:session:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
    assert rec["decided_by"] == expect
    assert rec["decided_by"] != "web_panel"
    assert rec.get("decision_channel") == "web_session"
    assert "token" not in rec  # 响应剥除令牌（只有 AI 侧 wait 可取）
    assert store.get(rid)["status"] == "approved"
    # 审计行含派生身份/通道/命令哈希
    decided = [line for line in _review_lines(isolated_data_dir) if line.get("outcome") == "decided"]
    assert decided[-1]["decided_by"] == expect
    assert decided[-1]["channel"] == "web_session"
    assert decided[-1]["command_sha256"] == sha


# ── 3. 客户端自报身份：忽略 + 审计 client_claimed_by ──


def test_client_claimed_identity_ignored_and_audited(client, store, isolated_data_dir):
    rid, sha = _pending(store)
    _login(client)
    r = client.post(
        _REVIEW,
        json={
            "id": rid,
            "decision": "approved",
            "expected_sha256": sha,
            "decided_by": "ceo-human-trust-me",
            "reviewer": "admin",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["request"]["decided_by"].startswith("web:session:")
    assert store.get(rid)["decided_by"].startswith("web:session:")  # 落盘同样不采信
    assert "ceo-human-trust-me" not in store.get(rid)["decided_by"]
    claimed = [line for line in _review_lines(isolated_data_dir) if line.get("client_claimed_by")]
    assert claimed and claimed[-1]["client_claimed_by"] == "ceo-human-trust-me"


# ── 4/5. 展示-审批绑定 ──


def test_stale_expected_sha256_conflict_keeps_pending(client, store):
    rid, _sha = _pending(store)
    _login(client)
    r = client.post(
        _REVIEW, json={"id": rid, "decision": "approved", "expected_sha256": "0" * 64}
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "stale_review"
    assert store.get(rid)["status"] == "pending"  # 失配不放行


def test_missing_expected_sha256_rejected(client, store):
    rid, _sha = _pending(store)
    _login(client)
    r = client.post(_REVIEW, json={"id": rid, "decision": "approved"})
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "missing_expected_sha256"
    assert store.get(rid)["status"] == "pending"


# ── 6. 批准闭环 + 重复审批 409 ──


def test_approved_token_reaches_wait_and_duplicate_review_conflicts(client, store):
    rid, sha = _pending(store)
    _login(client)
    r = client.post(_REVIEW, json={"id": rid, "decision": "approved", "expected_sha256": sha})
    assert r.status_code == 200, r.text
    token = store.get(rid)["token"]
    assert token  # 令牌已铸造（仅存储内可见）
    w = EscalationWaitTool(store=store)
    res = w.execute(request_id=rid, timeout_s=1)
    assert "已批准" in res.content and token in res.content  # AI 侧闭环可取
    # 重复审批（同 sha，状态已非 pending）→ 409 fail-closed 到首个决定
    r2 = client.post(_REVIEW, json={"id": rid, "decision": "denied", "expected_sha256": sha})
    assert r2.status_code == 409, r2.text
    assert store.get(rid)["status"] == "approved"


# ── 7. list 不泄露令牌 + 绑定字段齐备 ──


def test_list_never_leaks_token_and_carries_binding_fields(client, store):
    rid, sha = _pending(store)
    _login(client)
    assert client.post(_REVIEW, json={"id": rid, "decision": "approved", "expected_sha256": sha}).status_code == 200
    token = store.get(rid)["token"]
    r = client.get(_LIST)
    assert r.status_code == 200, r.text
    items = r.json()["requests"]
    hit = next(i for i in items if i["id"] == rid)
    assert "token" not in hit  # 键不存在
    assert token not in r.text  # 值不出现（含 token_expires_at 等相邻字段也无泄漏）
    assert hit["command_sha256"] == sha
    assert hit["command_len"] == len(_CMD)
    assert hit["command_truncated"] is False


def test_overlong_command_truncated_display_but_bound_by_full_sha(client, store):
    long_cmd = "echo " + "A" * 3000
    rid, sha = _pending(store, command=long_cmd)
    _login(client)
    items = client.get(_LIST).json()["requests"]
    hit = next(i for i in items if i["id"] == rid)
    assert hit["command_truncated"] is True
    assert len(hit["command"]) < len(long_cmd)  # 展示截断
    assert hit["command_len"] == len(long_cmd)  # 真实长度如实告知
    assert hit["command_sha256"] == sha  # 绑定的是完整原文 sha
    # 审批必须按完整原文 sha 才通过（截断视图 ≠ 绑定失效）
    r = client.post(_REVIEW, json={"id": rid, "decision": "approved", "expected_sha256": sha})
    assert r.status_code == 200, r.text
    assert store.get(rid)["command_sha256"] == sha


# ── 8. 未启用鉴权的本机回环（残余通道，如实标注）──


def test_loopback_noauth_review_uses_loopback_identity(build_test_engine, store, monkeypatch):
    for var in ("WEB_AUTH_REQUIRE", "WEB_API_KEY", "WEB_LOGIN_PASSWORD_HASH", "WEB_ORIGIN_ALLOWLIST"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    engine, _fake = build_test_engine([{"content": "ok"}])
    app = build_app(engine=engine)
    # 模拟本机回环直连（host 与 peer 均为 loopback，无代理头）
    loop = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 51423))
    rid, sha = _pending(store)
    r = loop.post(_REVIEW, json={"id": rid, "decision": "approved", "expected_sha256": sha})
    assert r.status_code == 200, r.text
    assert r.json()["request"]["decided_by"] == "web:loopback"
    assert r.json()["request"]["decision_channel"] == "loopback_unauthenticated"
    # 即使回环，仍要求 expected_sha256 绑定（不因免鉴权放宽）
    rid2, _sha2 = _pending(store, command="rm -rf /etc/esc-gate-unit-test-2")
    r2 = loop.post(_REVIEW, json={"id": rid2, "decision": "approved", "expected_sha256": "0" * 64})
    assert r2.status_code == 409 and r2.json()["error"] == "stale_review"
    assert store.get(rid2)["status"] == "pending"


# ── 8b. S0-2 杀伤链第 4 步实测：鉴权开启时，回环直连（无凭据/带 Bearer）
#        均不得审批——模型 shell 内 curl 回环的原始攻击路径被截断 ──


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-credential"),
        pytest.param({"Authorization": f"Bearer {_API_KEY}"}, id="bearer-from-loopback"),
    ],
)
def test_loopback_with_auth_enabled_cannot_review(build_test_engine, store, monkeypatch, headers):
    """WEB_AUTH_REQUIRE=1 时 require_api_key 放行 trusted-local，但审批端点
    仍要求可证明的人类通道：无会话 cookie → 403（Bearer 更是 AI 通道）。"""
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_API_KEY", _API_KEY)
    monkeypatch.delenv("WEB_LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("WEB_ORIGIN_ALLOWLIST", raising=False)
    engine, _fake = build_test_engine([{"content": "ok"}])
    app = build_app(engine=engine)
    loop = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 51424))
    rid, sha = _pending(store)
    r = loop.post(_REVIEW, headers=headers, json={"id": rid, "decision": "approved", "expected_sha256": sha})
    assert r.status_code == 403, r.text
    assert r.json()["error"] == "human_channel_required"
    assert store.get(rid)["status"] == "pending"


# ── 9. store 层兼容：旧调用方不传 expected_sha256 / decided_by ──


def test_store_decide_backward_compatible_without_new_args(store):
    """tools 侧/既有测试直调 decide（无 expected_sha256/decided_by）保持可用."""
    rid, _sha = _pending(store)
    pub, reason = store.decide(rid, "approved", note="legacy caller")
    assert pub is not None, reason
    rec = store.get(rid)
    assert rec["status"] == "approved"
    assert rec["decided_by"] == ""  # 不再伪造 web_panel，如实留空
    assert "token" not in pub


def test_store_decide_rejects_mismatched_expected_sha256(store):
    rid, _sha = _pending(store)
    pub, reason = store.decide(rid, "approved", decided_by="web:session:abcd1234",
                               channel="web_session", expected_sha256="f" * 64)
    assert pub is None and "stale_review" in reason
    assert store.get(rid)["status"] == "pending"
