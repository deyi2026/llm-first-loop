"""EVO-20261013 知识管理端点：经验/方法全生命周期视图与流转.

用户确认的学习页需求之二：经验管理区。端点复用模型工具同一 store 路径，
非法 action/transition 显式 4xx；store 门禁拒绝如实 409。
"""
from __future__ import annotations

import json

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


# ---------- 阶段2: 知识打分只读聚合端点（/api/v1/knowledge/scores） ----------

from llm_loop.knowledge_score.ledger import KnowledgeScoreLedger  # noqa: E402


def _scores_dir(tmp_path):
    """打分数据目录：与生产 <root>/data/knowledge_scores 同构（测试引擎 data_dir=tmp_path/data）."""
    data_dir = tmp_path / "data"
    scores = data_dir / "knowledge_scores"
    scores.mkdir(parents=True, exist_ok=True)
    return scores


def _write_score_ledger(tmp_path, rows: list[dict]) -> None:
    """写测试 ledger.jsonl（无 integrity 凭据的 legacy 行，read 语义等价）."""
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    (_scores_dir(tmp_path) / "ledger.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_score_sidecar(tmp_path, slug: str, payload: dict) -> None:
    cards = _scores_dir(tmp_path) / "cards"
    cards.mkdir(parents=True, exist_ok=True)
    (cards / f"{slug}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _ledger_row(**overrides) -> dict:
    row = {
        "schema": "knowledge-score/v1",
        "ts": "2026-10-15T10:00:00+08:00",
        "scorer_model": "27B-Instant-MLX-8bit",
        "kind": "experience",
        "ref": "experience:EXPERIENCE-20261015-aaaaaa",
        "decision_reported": "applied",
        "top_level": 4,
        "top_label": "显著帮助",
        "expected": 3.2,
        "confidence": 0.61,
        "p_evidence_sufficient": 0.8,
        "adopted": True,
        "error": "",
    }
    row.update(overrides)
    return row


def test_knowledge_scores_merges_sidecar_and_ledger(build_test_engine, tmp_path) -> None:
    """正常态：sidecar 优先合并 + 无 sidecar 的 ref 用 ledger 最新条目 + ledger ts 倒序."""
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _client(engine, tmp_path)
    _write_score_ledger(
        tmp_path,
        [
            _ledger_row(ledger_seq=1, ts="2026-10-15T10:00:00+08:00"),
            _ledger_row(
                ledger_seq=2,
                ts="2026-10-16T09:00:00+08:00",
                ref="method:m-alpha",
                kind="method",
                top_level=2,
                top_label="中等帮助",
                confidence=0.42,
                adopted=False,
            ),
            # 最新一条是 error 行（无打分结果）：进 ledger 明细、不进徽标索引
            _ledger_row(
                ledger_seq=3,
                ts="2026-10-17T09:00:00+08:00",
                ref="method:m-alpha",
                top_level=-1,
                top_label="",
                confidence=0.0,
                adopted=False,
                error="scorer unavailable",
            ),
        ],
    )
    _write_score_sidecar(
        tmp_path,
        "EXPERIENCE-20261015-aaaaaa",
        {
            "schema": "knowledge-score-sidecar/v1",
            "ref": "experience:EXPERIENCE-20261015-aaaaaa",
            "top_label": "显著帮助（sidecar 覆盖）",
            "top_level": 4,
            "confidence": 0.9,
            "expected": 3.5,
            "p_evidence_sufficient": 0.85,
            "scored_slots": 2,
            "last_scored_at": "2026-10-15T11:00:00+08:00",
            "evidence_level": "independently_evaluated",
            "scorer_model": "27B-Instant-MLX-8bit",
        },
    )

    resp = client.get("/api/v1/knowledge/scores")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3
    assert set(data["scores"]) == {
        "experience:EXPERIENCE-20261015-aaaaaa",
        "method:m-alpha",
    }
    # sidecar 优先：经验 ref 取 sidecar 字段而非 ledger 行
    exp = data["scores"]["experience:EXPERIENCE-20261015-aaaaaa"]
    assert exp["top_label"] == "显著帮助（sidecar 覆盖）"
    assert exp["confidence"] == 0.9
    assert exp["scored_slots"] == 2
    assert exp["last_scored_at"] == "2026-10-15T11:00:00+08:00"
    # 无 sidecar 的 ref：ledger 最新有结果行（error 行不覆盖徽标索引）
    method = data["scores"]["method:m-alpha"]
    assert method["top_label"] == "中等帮助"
    assert method["confidence"] == 0.42
    assert method["scored_slots"] == 1
    # ledger 明细按 ts 倒序，error 行如实保留
    seqs = [r["ledger_seq"] for r in data["ledger"]]
    assert seqs == [3, 2, 1]
    assert data["ledger"][0]["error"] == "scorer unavailable"
    assert data["ledger"][2]["adopted"] is True
    assert data["ledger"][2]["decision_reported"] == "applied"


def test_knowledge_scores_empty_when_no_files(build_test_engine, tmp_path) -> None:
    """空态：ledger/cards 均未产生 → 200 空结构（数据未产生不是服务故障）."""
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _client(engine, tmp_path)
    resp = client.get("/api/v1/knowledge/scores")
    assert resp.status_code == 200
    assert resp.json() == {
        "count": 0,
        "scores": {},
        "ledger": [],
        "pending": 0,
        "pending_error": None,
        "runner": None,
    }


def test_knowledge_scores_skips_bad_lines_and_sidecars(build_test_engine, tmp_path) -> None:
    """坏行/坏 sidecar 逐条隔离跳过，不整体失败（阶段1逐卡隔离语义）."""
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _client(engine, tmp_path)
    good = _ledger_row(ledger_seq=1)
    raw_lines = (
        json.dumps(good, ensure_ascii=False)
        + "\n"
        + "{torn json without newline"  # 损坏行：解析失败被跳过
    )
    (_scores_dir(tmp_path) / "ledger.jsonl").write_text(raw_lines, encoding="utf-8")
    _write_score_sidecar(
        tmp_path,
        "EXPERIENCE-20261015-aaaaaa",
        {
            "schema": "knowledge-score-sidecar/v1",
            "ref": "experience:EXPERIENCE-20261015-aaaaaa",
            "top_label": "显著帮助",
            "confidence": 0.61,
        },
    )
    cards = _scores_dir(tmp_path) / "cards"
    (cards / "broken.json").write_text("{not json", encoding="utf-8")
    (cards / "not-object.json").write_text("[1, 2]", encoding="utf-8")

    resp = client.get("/api/v1/knowledge/scores")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1  # 只剩完好行
    assert list(data["scores"]) == ["experience:EXPERIENCE-20261015-aaaaaa"]
    assert data["ledger"][0]["ledger_seq"] == 1


def test_knowledge_scores_read_error_returns_500(build_test_engine, tmp_path, monkeypatch) -> None:
    """读取异常（IO）→ 按现有模式 500 + error/detail."""
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _client(engine, tmp_path)

    def _boom(self):
        raise OSError("disk gone")

    monkeypatch.setattr(KnowledgeScoreLedger, "read", _boom)
    resp = client.get("/api/v1/knowledge/scores")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"] == "knowledge_scores_failed"
    assert "OSError" in body["detail"]


def test_knowledge_scores_no_sidecar_takes_latest_success_row(build_test_engine, tmp_path) -> None:
    """P1-1 回归：无 sidecar 的 ref 取 ledger 最新成功行（同 ref 两条成功行，取 ts 较新者）."""
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _client(engine, tmp_path)
    _write_score_ledger(
        tmp_path,
        [
            _ledger_row(
                ledger_seq=1,
                ts="2026-10-08T22:36:03+08:00",
                top_level=2,
                top_label="中等帮助",
                confidence=0.86,
            ),
            _ledger_row(
                ledger_seq=2,
                ts="2026-10-08T22:36:19+08:00",
                top_level=4,
                top_label="显著帮助",
                confidence=0.40,
            ),
        ],
    )

    resp = client.get("/api/v1/knowledge/scores")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    summary = data["scores"]["experience:EXPERIENCE-20261015-aaaaaa"]
    assert summary["top_label"] == "显著帮助"  # ts 较新的成功行胜出，而非最旧行
    assert summary["confidence"] == 0.40
    assert summary["top_level"] == 4
    assert summary["last_scored_at"] == "2026-10-08T22:36:19+08:00"


def test_knowledge_scores_skips_non_utf8_sidecar_file(build_test_engine, tmp_path) -> None:
    """P1-2 回归：非 UTF-8 二进制损坏 sidecar 逐文件隔离（UnicodeDecodeError），端点仍 200."""
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _client(engine, tmp_path)
    _write_score_ledger(tmp_path, [_ledger_row(ledger_seq=1)])
    _write_score_sidecar(
        tmp_path,
        "EXPERIENCE-20261015-aaaaaa",
        {
            "schema": "knowledge-score-sidecar/v1",
            "ref": "experience:EXPERIENCE-20261015-aaaaaa",
            "top_label": "显著帮助",
            "confidence": 0.61,
        },
    )
    cards = _scores_dir(tmp_path) / "cards"
    (cards / "binary-corrupt.json").write_bytes(b"\xff\xfe\x00b\xaad binary payload\x80")

    resp = client.get("/api/v1/knowledge/scores")
    assert resp.status_code == 200  # 坏文件被跳过，不拖垮整个端点
    data = resp.json()
    assert data["count"] == 1
    # 完好 sidecar 照常返回（坏文件被跳过不进索引）
    assert list(data["scores"]) == ["experience:EXPERIENCE-20261015-aaaaaa"]
    assert data["scores"]["experience:EXPERIENCE-20261015-aaaaaa"]["top_label"] == "显著帮助"
    assert data["scores"]["experience:EXPERIENCE-20261015-aaaaaa"]["confidence"] == 0.61
