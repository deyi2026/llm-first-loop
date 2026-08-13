"""P1-2 经验库集成测试: 端到端/零回归/既有kind不变（tasks 8.1-8.3）."""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.core.message import ToolResultStatus
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.status import ArchitectureStatusProvider


def _wire_components(audit_dir: Path, exp_dir: Path, *, exp_exists: bool = True):
    """装配 RecordSearcher + CorrectionToolRegistry + ExperienceStore（对齐 factory.py）。"""
    experience_store = ExperienceStore(exp_dir)
    searcher = RecordSearcher(audit_dir=audit_dir, experience_store=experience_store)
    ctx = CorrectionContext()
    status = ArchitectureStatusProvider(audit_dir=audit_dir, config_status=lambda: {})
    corrections = CorrectionToolRegistry(ctx, audit_dir=audit_dir, status_provider=status)
    corrections._search_records_fn = lambda **kw: searcher.search(**kw)  # noqa: SLF001
    if exp_exists:
        corrections._experience_store = experience_store  # noqa: SLF001
    return searcher, corrections, experience_store


# ── 8.1 save_experience → search_records(kind=experience) 端到端 ──


def test_save_then_search_experience_end_to_end(tmp_path):
    """AI 调 save_experience 沉淀 → search_records(kind=experience) 检索 → 能查到（含来源溯源）。"""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    exp_dir = tmp_path / "experiences"
    searcher, corrections, _ = _wire_components(audit_dir, exp_dir)

    # 1. AI 调 save_experience 沉淀经验
    save_result = corrections.execute(
        "save_experience",
        {
            "title": "stream-render-fix",
            "scenario": "Web前端思考过程不显示",
            "root_cause": "SSE事件未透传reasoning_delta",
            "solution": "在event_stream增加reasoning_delta事件",
            "evidence": "tests/web/test_reasoning_render.py",
            "tags": ["web", "sse", "reasoning"],
            "source": {"session": "s1", "task": "P1-1"},
            "body": "## 根因\nSSE缺少reasoning_delta事件。\n## 解法\n在routes.py增加事件发射。",
        },
    )
    assert save_result.status == ToolResultStatus.SUCCESS
    assert "[save_experience]" in save_result.content
    assert "EXPERIENCE-" in save_result.content

    # 2. AI 调 search_records(kind=experience) 检索
    search_result = corrections.execute(
        "search_records",
        {"kind": "experience", "query": "stream", "limit": 10},
    )
    assert search_result.status == ToolResultStatus.SUCCESS
    # 解析回执中的检索结果
    assert "stream-render-fix" in search_result.content or "experience" in search_result.content

    # 3. 直接调 searcher 验证结构化记录含来源溯源字段
    records = searcher.search(kind="experience", query="stream")
    assert len(records) == 1
    rec = records[0]
    assert rec["kind"] == "experience"
    assert rec["source"] == {"session": "s1", "task": "P1-1"}
    assert rec["tags"] == ["web", "sse", "reasoning"]
    assert rec["status"] == "active"


def test_save_then_search_with_source_tracing(tmp_path):
    """检索返回经验条目含来源溯源 source 字段（spec 5.2.1 规则 5a）。"""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    exp_dir = tmp_path / "experiences"
    searcher, corrections, _ = _wire_components(audit_dir, exp_dir)

    corrections.execute(
        "save_experience",
        {
            "title": "source-trace-test",
            "scenario": "场景",
            "solution": "解法",
            "source": {"origin": "ai-analysis", "round": "3"},
        },
    )
    results = searcher.search(kind="experience", query="source")
    assert len(results) == 1
    assert results[0]["source"] == {"origin": "ai-analysis", "round": "3"}


# ── 8.2 experiences/ 目录不存在零回归 ──


def test_exp_dir_not_exist_search_returns_empty(tmp_path):
    """experiences/ 目录不存在时 search_records(kind=experience) 如实返回未命中。"""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    exp_dir = tmp_path / "nonexistent-exp"
    searcher, corrections, _ = _wire_components(audit_dir, exp_dir)

    results = searcher.search(kind="experience", query="anything")
    assert results == []

    # 通过工具分派也如实返回未命中
    tool_result = corrections.execute("search_records", {"kind": "experience", "query": "anything"})
    assert tool_result.status == ToolResultStatus.SUCCESS


def test_exp_dir_not_exist_existing_kinds_unaffected(tmp_path):
    """experiences/ 目录不存在时既有 memory/docs/检索不受影响（零回归）。"""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    # 写入 action_trace 记录
    (audit_dir / "action_trace.jsonl").write_text(
        json.dumps({"ts": "2026-08-13T10:00:00", "id": "a1", "phase": "test", "action_type": "call", "detail": "read file"})
        + "\n",
        encoding="utf-8",
    )
    exp_dir = tmp_path / "nonexistent-exp"
    searcher, _, _ = _wire_components(audit_dir, exp_dir)

    # action_trace 检索正常工作
    results = searcher.search(kind="action_trace", query="read")
    assert len(results) == 1
    assert results[0]["kind"] == "action_trace"

    # experience 检索返回空
    assert searcher.search(kind="experience") == []

    # kind=all 仍返回既有 kind，不含 experience
    all_results = searcher.search(kind="all", limit=20)
    kinds = {r["kind"] for r in all_results}
    assert "action_trace" in kinds
    assert "experience" not in kinds


def test_exp_dir_not_exist_save_still_works(tmp_path):
    """experiences/ 目录不存在时 save_experience 仍可写入（自动创建目录）。"""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    exp_dir = tmp_path / "auto-create-exp"
    _, corrections, _ = _wire_components(audit_dir, exp_dir)

    result = corrections.execute(
        "save_experience",
        {"title": "auto-create-test", "scenario": "场景", "solution": "解法"},
    )
    assert result.status == ToolResultStatus.SUCCESS
    assert exp_dir.exists()


# ── 8.3 既有 kind 检索行为不变 ──


def test_existing_kinds_unchanged_with_experience_store(tmp_path):
    """接入 experience_store 后既有 kind 检索结果与接入前完全一致。"""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    # 写入多种既有记录
    (audit_dir / "action_trace.jsonl").write_text(
        json.dumps({"ts": "2026-08-13T10:00:00", "id": "a1", "phase": "p1", "action_type": "call", "detail": "read file"})
        + "\n",
        encoding="utf-8",
    )
    (audit_dir / "exception_log.jsonl").write_text(
        json.dumps({"ts": "2026-08-13T10:01:00", "id": "e1", "phase": "p1", "error_type": "ValueError", "error_message": "boom"})
        + "\n",
        encoding="utf-8",
    )

    exp_dir = tmp_path / "exp"
    # 有 experience_store
    searcher_with_exp = RecordSearcher(audit_dir=audit_dir, experience_store=ExperienceStore(exp_dir))
    # 无 experience_store
    searcher_without_exp = RecordSearcher(audit_dir=audit_dir)

    for kind in ("action_trace", "exception_log"):
        with_exp = searcher_with_exp.search(kind=kind, query="")
        without_exp = searcher_without_exp.search(kind=kind, query="")
        assert with_exp == without_exp, f"kind={kind} 检索结果因 experience_store 接入而变化"

    # kind=all 既有 kind 部分一致（experience 部分新增但不影响既有）
    all_with = [r for r in searcher_with_exp.search(kind="all", limit=20) if r["kind"] != "experience"]
    all_without = searcher_without_exp.search(kind="all", limit=20)
    assert all_with == all_without


def test_kind_all_experience_parallel_with_existing(tmp_path):
    """kind=all 时 experience 与既有 kind 并列返回，kind 区分不混淆。"""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    (audit_dir / "action_trace.jsonl").write_text(
        json.dumps({"ts": "2026-08-13T10:00:00", "id": "a1", "phase": "p1", "action_type": "call", "detail": "parallel test"})
        + "\n",
        encoding="utf-8",
    )
    exp_dir = tmp_path / "exp"
    store = ExperienceStore(exp_dir)
    from llm_loop.experiences.document import ExperienceDocument

    store.save(
        ExperienceDocument(
            title="parallel-exp",
            scenario="场景",
            root_cause="",
            solution="解法",
            evidence="",
            tags=[],
            source={},
            body="",
        )
    )
    searcher = RecordSearcher(audit_dir=audit_dir, experience_store=store)
    results = searcher.search(kind="all", limit=20)
    kinds = {r["kind"] for r in results}
    assert "action_trace" in kinds
    assert "experience" in kinds
    # kind 区分不混淆
    for r in results:
        if r["kind"] == "experience":
            assert r["summary"] == "parallel-exp"
        elif r["kind"] == "action_trace":
            assert "parallel test" in r["summary"]
