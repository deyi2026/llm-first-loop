"""EVO-20261013 知识管理端点：经验/方法全生命周期视图与流转.

用户确认的学习页需求之二：经验管理区。端点复用模型工具同一 store 路径，
非法 action/transition 显式 4xx；store 门禁拒绝如实 409。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.methods.store import MethodStore
from llm_loop.web import build_app


def _seed_experience(store: ExperienceStore, title: str) -> str:
    name = store.save(
        ExperienceDocument(
            title=title,
            scenario="scenario for management",
            root_cause="root cause",
            solution="solution",
            evidence="fixture:evidence",
            tags=["mgmt"],
            source={"kind": "fixture"},
            status="active",
            record_kind="experience",
            verification_state="verified",
            body="当前性验证：pytest tests/web/test_knowledge_endpoints.py 应全绿",
        )
    )
    return name.removesuffix(".md")  # raw stem：store 层语义；路由负责 experience: 归一


def _seed_method(root, method_id: str, *, status: str = "candidate") -> None:
    d = root / method_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "METHOD.md").write_text(
        "---\n"
        f"method_id: {method_id}\n"
        f"name: {method_id}\n"
        f"description: diagnostic method {method_id}\n"
        f"status: {status}\n"
        "---\n"
        "BODY\n",
        encoding="utf-8",
    )


def _client(engine, tmp_path):
    engine.corrections._experience_store = ExperienceStore(tmp_path / "experiences")  # noqa: SLF001
    engine.corrections._method_store = MethodStore(tmp_path / "methods")  # noqa: SLF001
    return TestClient(build_app(engine=engine))


def test_experience_catalog_lists_all_lifecycle_states(build_test_engine, tmp_path) -> None:
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _client(engine, tmp_path)
    store = engine.corrections._experience_store  # noqa: SLF001
    ref_a = _seed_experience(store, "active one")
    ref_b = _seed_experience(store, "to archive")
    assert store.update_status(ref_b, "archived")  # store 层用 raw stem ref

    resp = client.get("/api/v1/knowledge/experiences")
    assert resp.status_code == 200
    data = resp.json()
    assert data["counts"]["active"] == 1
    assert data["counts"]["archived"] == 1
    summaries = {r["summary"] for r in data["records"]}
    assert "active one" in summaries

    # status 过滤
    resp_arch = client.get("/api/v1/knowledge/experiences", params={"status": "archived"})
    assert {r["summary"] for r in resp_arch.json()["records"]} == {"to archive"}
    assert ref_a.startswith("EXPERIENCE-")  # raw stem


def test_experience_catalog_usage_stats(build_test_engine, tmp_path) -> None:
    """EVO-20261013 知识页：catalog 投影 use_count / last_used_at（账本聚合）."""
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _client(engine, tmp_path)
    store = engine.corrections._experience_store  # noqa: SLF001
    ref_a = _seed_experience(store, "used one")
    _ref_b = _seed_experience(store, "never used")  # noqa: F841 — 对照组（use_count=0 分支）

    store.record_use(ref_a, use_decision="applied", note="first")
    store.record_use(ref_a, use_decision="adapted", note="second")

    resp = client.get("/api/v1/knowledge/experiences")
    assert resp.status_code == 200
    by_summary = {r["summary"]: r for r in resp.json()["records"]}

    used = by_summary["used one"]
    assert used["use_count"] == 2
    assert used["last_used_at"]  # 有值即可：ts 由运行时生成，断言非空且 >= created
    fresh = by_summary["never used"]
    assert fresh["use_count"] == 0
    assert fresh["last_used_at"] is None


def test_experience_detail_and_404(build_test_engine, tmp_path) -> None:
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _client(engine, tmp_path)
    store = engine.corrections._experience_store  # noqa: SLF001
    ref = _seed_experience(store, "detail target")

    ok = client.get(f"/api/v1/knowledge/experiences/{ref}")  # 带 experience: 前缀由路由归一
    assert ok.status_code == 200
    assert ok.json()["summary"] == "detail target"
    assert ok.json()["body"]

    missing = client.get("/api/v1/knowledge/experiences/experience:EXPERIENCE-nope")
    assert missing.status_code == 404


def test_experience_lifecycle_archive_and_restore(build_test_engine, tmp_path) -> None:
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _client(engine, tmp_path)
    store = engine.corrections._experience_store  # noqa: SLF001
    ref = _seed_experience(store, "lifecycle target")

    bad = client.post(f"/api/v1/knowledge/experiences/{ref}/lifecycle", params={"action": "bogus"})
    assert bad.status_code == 422

    archived = client.post(f"/api/v1/knowledge/experiences/{ref}/lifecycle", params={"action": "archive"})
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert store.get(ref).status == "archived"
    # invalidate 走与模型工具一致的 "invalid" 语义
    invalidated = client.post(f"/api/v1/knowledge/experiences/{ref}/lifecycle", params={"action": "invalidate"})
    assert invalidated.json()["status"] == "invalid"

    restored = client.post(f"/api/v1/knowledge/experiences/{ref}/lifecycle", params={"action": "restore"})
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"

    missing = client.post(
        "/api/v1/knowledge/experiences/experience:EXPERIENCE-nope/lifecycle",
        params={"action": "archive"},
    )
    assert missing.status_code == 404


def test_method_inventory_and_detail(build_test_engine, tmp_path) -> None:
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _client(engine, tmp_path)
    _seed_method(tmp_path / "methods", "inv-candidate-a")
    _seed_method(tmp_path / "methods", "inv-hold-b", status="hold")

    resp = client.get("/api/v1/knowledge/methods")
    assert resp.status_code == 200
    data = resp.json()
    assert data["counts"]["candidate"] == 1
    assert data["counts"]["hold"] == 1

    detail = client.get("/api/v1/knowledge/methods/method:inv-candidate-a")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "candidate"
    assert "qualification_entries" in body
    assert "freshness" in body

    assert client.get("/api/v1/knowledge/methods/method:inv-missing").status_code == 404


def test_method_transition_gates(build_test_engine, tmp_path) -> None:
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _client(engine, tmp_path)
    _seed_method(tmp_path / "methods", "gate-candidate")

    bad = client.post(
        "/api/v1/knowledge/methods/method:gate-candidate/transition", params={"transition": "bogus"}
    )
    assert bad.status_code == 422

    # candidate → active：无 2 类任务 pass qualification，store 门禁拒绝 → 409
    denied = client.post(
        "/api/v1/knowledge/methods/method:gate-candidate/transition", params={"transition": "activate"}
    )
    assert denied.status_code == 409

    # candidate → hold：合法流转
    held = client.post(
        "/api/v1/knowledge/methods/method:gate-candidate/transition", params={"transition": "hold"}
    )
    assert held.status_code == 200
    assert held.json()["status"] == "hold"


def test_learning_status_carries_observability_fields(build_test_engine, tmp_path, monkeypatch) -> None:
    """learning/status 扩展字段：oldest_queued / admission / requeue_stats 键存在（fail-open）."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, _ = build_test_engine([{"content": "你好"}])
    client = TestClient(build_app(engine=engine))
    resp = client.get("/api/v1/learning/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "oldest_queued" in data
    assert "admission" in data
    assert "requeue_stats" in data
    # 测试引擎无 journal/心跳：全部优雅降级而非 5xx
    assert data["oldest_queued"] is None
    assert data["admission"]["present"] is False
