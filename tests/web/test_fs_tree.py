"""文件树/会话树 API 测试（EVO-20260818 DSH 064）.

覆盖:
- A 文件树: GET tree（目录+文件）；mkdir/rename/delete（confirm 两步 + 越界拒绝）
- B 会话树: GET agents/tree（会话→子代理层级）
- 安全: 越界路径拒绝、危险路径拒绝、confirm_required
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from llm_loop.web import build_app


@pytest.fixture()
def client(tmp_path):
    """构造隔离工作区引擎的测试客户端."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMClient
    from llm_loop.tools.registry import ToolRegistry

    data_dir = tmp_path / "data"
    # data_dir 由 Settings 构造时自动 mkdir；sessions/audit 从 data_dir 派生
    settings = Settings(
        llm_api_key="k", llm_base_url="http://t", llm_model="m",
        data_dir=str(data_dir),
    )
    (tmp_path / "ws").mkdir(exist_ok=True)
    engine = LoopEngine(
        llm_client=LLMClient(api_key="k", base_url="http://t", model="m"),
        registry=ToolRegistry(),
        memory=None,
        session=SessionStore(data_dir / "sessions"),
        settings=settings,
    )
    engine.workspace_root = str(tmp_path / "ws")
    app = build_app(engine=engine)
    app.state.engine = engine
    return TestClient(app), engine


# ── A 文件树 ──
def test_fs_tree_lists_dirs_and_files(client, tmp_path):
    cli, engine = client
    ws = tmp_path / "ws"
    (ws / "sub").mkdir()
    (ws / "file.txt").write_text("hi", encoding="utf-8")
    (ws / ".hidden").write_text("x", encoding="utf-8")
    r = cli.get("/api/v1/fs/tree", params={"path": ""})
    assert r.status_code == 200
    d = r.json()
    assert "sub" in d["dirs"]
    assert any(f["name"] == "file.txt" for f in d["files"])
    assert ".hidden" not in [f["name"] for f in d["files"]]  # 忽略隐藏


def test_fs_tree_out_of_bounds(client):
    cli, _ = client
    r = cli.get("/api/v1/fs/tree", params={"path": "/etc/passwd"})
    assert r.status_code == 400
    assert r.json()["error"] == "out_of_bounds"


def test_fs_mkdir(client, tmp_path):
    cli, _ = client
    r = cli.post("/api/v1/fs/mkdir", params={"path": "new_dir"})
    assert r.status_code == 200
    assert (tmp_path / "ws" / "new_dir").is_dir()


def test_fs_rename(client, tmp_path):
    cli, _ = client
    (tmp_path / "ws" / "a.txt").write_text("x", encoding="utf-8")
    r = cli.put("/api/v1/fs/rename", params={"path": "a.txt", "new_name": "b.txt"})
    assert r.status_code == 200
    assert (tmp_path / "ws" / "b.txt").exists()
    assert not (tmp_path / "ws" / "a.txt").exists()


def test_fs_delete_requires_confirm(client, tmp_path):
    cli, _ = client
    (tmp_path / "ws" / "del.txt").write_text("x", encoding="utf-8")
    # 无 confirm → 409
    r = cli.delete("/api/v1/fs/delete", params={"path": "del.txt"})
    assert r.status_code == 409
    assert r.json()["error"] == "confirm_required"
    assert (tmp_path / "ws" / "del.txt").exists()  # 未删除


def test_fs_delete_with_confirm(client, tmp_path):
    cli, _ = client
    (tmp_path / "ws" / "del.txt").write_text("x", encoding="utf-8")
    # P0-2 两步令牌：先 GET delete-token，再带 token + confirm=true 删除
    tok = cli.get("/api/v1/fs/delete-token", params={"path": "del.txt"})
    assert tok.status_code == 200
    token = tok.json()["token"]
    r = cli.delete(
        "/api/v1/fs/delete",
        params={"path": "del.txt", "confirm": "true", "token": token},
    )
    assert r.status_code == 200
    assert not (tmp_path / "ws" / "del.txt").exists()
    # 令牌单次使用：同一 token 不能重放
    replay = cli.delete(
        "/api/v1/fs/delete",
        params={"path": "del.txt", "confirm": "true", "token": token},
    )
    assert replay.status_code == 409


def test_fs_delete_dangerous_denied(client):
    cli, _ = client
    # P0-2 后危险路径在令牌签发阶段即被拒（删除端点仍独立复核，纵深防御）
    r = cli.get("/api/v1/fs/delete-token", params={"path": "../../etc/passwd"})
    assert r.status_code == 400
    assert r.json()["error"] == "out_of_bounds"


def test_fs_audit_written(client, tmp_path):
    cli, _ = client
    cli.post("/api/v1/fs/mkdir", params={"path": "audited"})
    # audit 落在 data_dir/audit（settings.audit_dir 属性派生）
    audit = tmp_path / "data" / "audit" / "fs_operations.jsonl"
    assert audit.exists()
    assert "mkdir" in audit.read_text(encoding="utf-8")


# ── B 会话树 ──
def test_agents_tree_lists_sessions(client):
    cli, engine = client
    sid = engine.session.create()
    # 造一个子代理会话（带 parent_id，模拟 fork/子代理）
    sub = engine.session.create()
    try:
        sess = engine.session.load(sub)
        sess.parent_id = sid
        engine.session.save(sess)
    except Exception:
        # 测试夹具：子代理会话的 parent_id 回写不可用不影响本用例的树渲染断言
        pass
    r = cli.get("/api/v1/agents/tree")
    assert r.status_code == 200
    nodes = {n["id"]: n for n in r.json()["nodes"]}
    assert sid in nodes
    assert sub in nodes
    assert nodes[sub]["parent_id"] == sid


def test_agents_tree_empty(client):
    cli, _ = client
    r = cli.get("/api/v1/agents/tree")
    assert r.status_code == 200
    assert r.json()["nodes"] == []


# ── 演进审批 API ──
def test_evolution_review_accept(client, tmp_path):
    """web 审批: accepted → 状态机流转 + 回执."""
    cli, engine = client
    # 构造 production authority path 上的 evolution_store
    from llm_loop.introspection.evolution import EvolutionStore

    st = EvolutionStore(tmp_path / "data" / "audit")
    st.submit(content="web 审批测试建议", evidence="ev", impact_scope="core", priority="low")
    engine.correction_ctx = SimpleNamespace(
        evolution_store=st,
        evolve_local_exec=0,
        evolve_exec_whitelist="",
    )
    sid = st.list()[0]["id"]

    r = cli.post("/api/v1/evolution/review", json={"id": sid, "decision": "accepted"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and "已批准" in d["message"]
    assert st.list()[0]["status"] == "accepted"


def test_evolution_review_reject_with_reason(client, tmp_path):
    cli, engine = client
    from llm_loop.introspection.evolution import EvolutionStore

    st = EvolutionStore(tmp_path / "data" / "audit")
    st.submit(content="web 拒绝测试", evidence="ev", impact_scope="core", priority="low")
    engine.correction_ctx = SimpleNamespace(
        evolution_store=st,
        evolve_local_exec=0,
        evolve_exec_whitelist="",
    )
    sid = st.list()[0]["id"]

    r = cli.post("/api/v1/evolution/review", json={"id": sid, "decision": "rejected", "reason": "不成熟"})
    assert r.status_code == 200
    assert r.json()["ok"] is True and "已拒绝" in r.json()["message"]
    assert st.list()[0]["status"] == "rejected"


def test_evolution_review_invalid_params(client):
    cli, _ = client
    # decision 非法 → Pydantic pattern 校验拦下（422）
    r = cli.post("/api/v1/evolution/review", json={"id": "EVO-x", "decision": "maybe"})
    assert r.status_code == 422
    # 缺 id → 422（min_length 校验）
    r2 = cli.post("/api/v1/evolution/review", json={"id": "", "decision": "accepted"})
    assert r2.status_code == 422


def test_evolution_review_store_on_correction_ctx(client, tmp_path):
    """回归（EVO-20260909 web 审批确认键无效）：store 按 factory.py 真实装配位置挂在 correction_ctx 上，review 必须可用.

    旧实现读 getattr(engine, "evolution_store")，生产引擎该属性恒不存在 → 恒 400 evolve_disabled
    （面板列表读文件有数据、弹框确认却无效）。本测试不复刻测试夹具的直挂 engine 掩盖路径。
    """
    cli, engine = client
    from llm_loop.introspection.corrections import CorrectionContext
    from llm_loop.introspection.evolution import EvolutionStore

    st = EvolutionStore(tmp_path / "data" / "audit")
    st.submit(content="装配位置回归测试", evidence="ev", impact_scope="core", priority="low")
    sid = st.list()[0]["id"]

    ctx = CorrectionContext()
    ctx.evolution_store = st
    engine.correction_ctx = ctx
    try:
        r = cli.post("/api/v1/evolution/review", json={"id": sid, "decision": "accepted"})
        assert r.status_code == 200, f"review 应成功，实际 {r.status_code}: {r.text}"
        d = r.json()
        assert d["ok"] is True and "已批准" in d["message"]
        assert st.list()[0]["status"] == "accepted"
    finally:
        engine.correction_ctx = None


def test_agents_tree_uses_meta_only_no_full_load(client, monkeypatch):
    """CPU 契约（2026-09-22 web 100% 事故）：agents/tree 只读 metas.

    460 会话/324MB 下每请求逐会话全量 load = 2.2s CPU；目录面板 1s 心跳 ×
    多标签页即饱和一核并阻塞事件循环。parent_id 等字段必须经 SessionMeta
    透传到达，端点不得调用 session.load()。
    """
    cli, engine = client
    sid = engine.session.create()
    sub = engine.session.create()
    sess = engine.session.load(sub)
    sess.parent_id = sid
    engine.session.save(sess)

    calls = {"n": 0}
    orig = engine.session.load

    def counting_load(s):
        calls["n"] += 1
        return orig(s)

    monkeypatch.setattr(engine.session, "load", counting_load)
    r = cli.get("/api/v1/agents/tree")
    assert r.status_code == 200
    nodes = {n["id"]: n for n in r.json()["nodes"]}
    assert nodes[sub]["parent_id"] == sid
    assert calls["n"] == 0


def test_delta_relay_coalesces_same_channel_burst():
    """CPU 契约（2026-09-23 #1）：同通道 delta 突发合并为一帧 SSE.

    长 reasoning 流逐 chunk json.dumps+write 是 run 期间主线程残余负载的大头；
    合并窗口内连续 text delta 应合并为单帧（拼接顺序保序）。
    """
    import queue as _q
    from types import SimpleNamespace

    from llm_loop.web import routes as _routes

    q: _q.Queue = _q.Queue()
    for piece in ("阿尔法", "贝塔", "伽马"):
        q.put({"type": "delta", "delta": SimpleNamespace(text=piece, reasoning=None)})
    q.put(
        {
            "type": "done",
            "result": SimpleNamespace(
                session_id="s", final_answer="ok", rounds=1, tool_calls=0,
                truncated=False, history_compacted=False,
                provider_output_truncated=False, run_incomplete=False,
                projection_validator_failed=False, projection_rebuilt=False,
                projection_cannot_fit=False, model_used="m",
                tokens_in=1, tokens_out=1, tokens_cache_hit=0,
                reasoning_content="", reasoning_mode="auto",
                reasoning_capable=False, reasoning_control="unknown",
                reasoning_supported=False, reasoning_effective=False,
                reasoning_tokens=None,
            ),
        }
    )

    class _Runner:
        enabled = True

        def start(self, sid, message, **kw):
            return SimpleNamespace(run_generation="g1"), q

        def unsubscribe(self, sid, qq):
            pass

    frames = []
    for chunk in _routes._stream_background(_Runner(), "s", "hi", None):
        if chunk.startswith("data:"):
            import json as _json

            frames.append(_json.loads(chunk[5:].strip()))

    deltas = [f for f in frames if f["type"] == "answer_delta"]
    assert len(deltas) == 1, f"3 个同通道突发 delta 应合并为 1 帧，实际 {len(deltas)}"
    assert deltas[0]["data"]["data"] == "阿尔法贝塔伽马"
    assert frames[-1]["type"] == "done"


# ── M3 验收后续：agents/tree 进程内 TTL 缓存（源站 5-13s）──
def test_agents_tree_ttl_cache_hit_skips_recompute(client, monkeypatch):
    """30s TTL 内重复请求命中缓存不重算；响应字节等价；TTL 过期重算."""
    from llm_loop.web import fs_tree as fs_tree_mod

    fs_tree_mod._reset_agents_tree_cache_for_tests()
    cli, engine = client
    sid1 = engine.session.create()
    calls = {"n": 0}
    orig = engine.session.list_sessions

    def counting_list_sessions(*args, **kwargs):  # noqa: ANN002, ANN003
        calls["n"] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(engine.session, "list_sessions", counting_list_sessions)
    r1 = cli.get("/api/v1/agents/tree")
    assert r1.status_code == 200
    assert calls["n"] == 1
    assert sid1 in {n["id"] for n in r1.json()["nodes"]}

    # TTL 窗口内新落盘会话不触发重算；命中缓存且响应字节等价（30s 内陈旧是契约语义）
    sid2 = engine.session.create()
    r2 = cli.get("/api/v1/agents/tree")
    assert calls["n"] == 1
    assert r2.content == r1.content
    assert sid2 not in {n["id"] for n in r2.json()["nodes"]}

    # TTL 过期 → 重算，新会话可见
    with fs_tree_mod._agents_tree_cache_lock:
        key = next(iter(fs_tree_mod._agents_tree_cache))
        cached_at, cached_engine, payload = fs_tree_mod._agents_tree_cache[key]
        fs_tree_mod._agents_tree_cache[key] = (
            cached_at - fs_tree_mod._AGENTS_TREE_CACHE_TTL_SECONDS,
            cached_engine,
            payload,
        )
    r3 = cli.get("/api/v1/agents/tree")
    assert calls["n"] == 2
    assert sid2 in {n["id"] for n in r3.json()["nodes"]}


def test_agents_tree_cache_not_populated_on_error(client, monkeypatch):
    """list_sessions 失败 → 500 不入缓存；恢复后立即重算成功."""
    from llm_loop.web import fs_tree as fs_tree_mod

    fs_tree_mod._reset_agents_tree_cache_for_tests()
    cli, engine = client
    sid = engine.session.create()
    orig = engine.session.list_sessions

    def boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("list boom")

    monkeypatch.setattr(engine.session, "list_sessions", boom)
    r = cli.get("/api/v1/agents/tree")
    assert r.status_code == 500
    assert fs_tree_mod._agents_tree_cache == {}  # 失败不缓存 → 下次调用即重算

    # 显式恢复（monkeypatch.undo() 会连带撤销 conftest 鉴权隔离，勿用）
    monkeypatch.setattr(engine.session, "list_sessions", orig)
    r2 = cli.get("/api/v1/agents/tree")
    assert r2.status_code == 200
    assert sid in {n["id"] for n in r2.json()["nodes"]}


def test_agents_tree_cache_is_per_engine_and_bounded():
    from llm_loop.web import fs_tree as fs_tree_mod

    fs_tree_mod._reset_agents_tree_cache_for_tests()
    try:
        e1, e2 = object(), object()
        fs_tree_mod._agents_tree_cache_put(e1, {"nodes": [{"id": "a"}]})
        assert fs_tree_mod._agents_tree_cache_get(e1) == {"nodes": [{"id": "a"}]}
        # 不同 engine 不共享（缓存值持有 engine 强引用，id 复用不会串数据）
        assert fs_tree_mod._agents_tree_cache_get(e2) is None
        for i in range(10):
            fs_tree_mod._agents_tree_cache_put(object(), {"i": i})
        assert len(fs_tree_mod._agents_tree_cache) <= 8  # 有界（生产进程实际 = 1 个 engine）
    finally:
        fs_tree_mod._reset_agents_tree_cache_for_tests()
