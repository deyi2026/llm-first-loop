"""P1-2 经验库单元测试: 文档模型/YAML解析/存储组件/检索接入/工具逻辑（tasks 7.1-7.7）."""

from __future__ import annotations

import pytest

from llm_loop.experiences.document import ExperienceDocument, ExperienceParseError
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.tools_experience import run_refine_experience, run_save_experience

# ── 7.1 ExperienceDocument to_md/from_md 往返 ──


def test_document_round_trip_all_fields():
    """to_md → from_md 往返还原一致（所有结构化字段 + body）。"""
    doc = ExperienceDocument(
        title="修复流式思考渲染丢失",
        scenario="Web前端思考过程不显示",
        root_cause="SSE事件未透传reasoning_delta",
        solution="在event_stream增加reasoning_delta事件",
        evidence="tests/web/test_reasoning_render.py",
        tags=["web", "sse", "reasoning"],
        source={"session": "s1", "task": "P1-1"},
        status="active",
        created_at="2026-08-13T10:00:00+08:00",
        updated_at="2026-08-13T10:30:00+08:00",
        body="## 根因分析\n\nSSE事件流缺少reasoning_delta类型。\n\n## 解决方案\n\n在routes.py的event_stream中增加reasoning_delta事件发射。",
    )
    md = doc.to_md()
    restored = ExperienceDocument.from_md(md)
    assert restored.title == doc.title
    assert restored.scenario == doc.scenario
    assert restored.root_cause == doc.root_cause
    assert restored.solution == doc.solution
    assert restored.evidence == doc.evidence
    assert restored.tags == doc.tags
    assert restored.source == doc.source
    assert restored.status == doc.status
    assert restored.created_at == doc.created_at
    assert restored.updated_at == doc.updated_at
    assert restored.body == doc.body


def test_document_round_trip_empty_source_and_body():
    """空 source + 空 body 往返不丢失。"""
    doc = ExperienceDocument(
        title="空体经验",
        scenario="场景",
        root_cause="",
        solution="解法",
        evidence="",
        tags=[],
        source={},
    )
    restored = ExperienceDocument.from_md(doc.to_md())
    assert restored.source == {}
    assert restored.body == ""
    assert restored.tags == []
    assert restored.status == "active"


def test_document_default_status_active():
    """status 默认 active。"""
    doc = ExperienceDocument(title="t", scenario="s", root_cause="", solution="sol", evidence="", tags=[], source={})
    assert doc.status == "active"


# ── 7.2 极简 YAML 解析器 ──


def test_yaml_parser_key_value():
    """key: value 格式正确解析。"""
    md = "---\ntitle: 简单标题\nscenario: 场景描述\nstatus: active\n---\n正文"
    doc = ExperienceDocument.from_md(md)
    assert doc.title == "简单标题"
    assert doc.scenario == "场景描述"
    assert doc.status == "active"
    assert doc.body == "正文"


def test_yaml_parser_list_value():
    """key: [a, b] 列表格式正确解析。"""
    md = "---\ntitle: t\ntags: [python, web, sse]\n---\n"
    doc = ExperienceDocument.from_md(md)
    assert doc.tags == ["python", "web", "sse"]


def test_yaml_parser_nested_block():
    """key: 缩进块嵌套 dict 正确解析。"""
    md = "---\ntitle: t\nsource:\n  session: s1\n  task: P1-2\n---\n"
    doc = ExperienceDocument.from_md(md)
    assert doc.source == {"session": "s1", "task": "P1-2"}


def test_yaml_parser_quoted_value_with_colon():
    """含冒号的值加引号解析正确。"""
    md = '---\ntitle: "含:冒号标题"\n---\n'
    doc = ExperienceDocument.from_md(md)
    assert doc.title == "含:冒号标题"


def test_yaml_parser_missing_front_matter_start():
    """缺少 front matter 起始标记抛 ExperienceParseError。"""
    with pytest.raises(ExperienceParseError, match="起始标记"):
        ExperienceDocument.from_md("title: t\n---\n正文")


def test_yaml_parser_missing_front_matter_end():
    """缺少 front matter 结束标记抛 ExperienceParseError。"""
    with pytest.raises(ExperienceParseError, match="结束标记"):
        ExperienceDocument.from_md("---\ntitle: t\n正文")


def test_yaml_parser_illegal_line():
    """front matter 行格式非法抛 ExperienceParseError。"""
    with pytest.raises(ExperienceParseError, match="非法"):
        ExperienceDocument.from_md("---\n  bad indent line\n---\n")


# ── 7.3 ExperienceStore.save ──


def test_save_filename_kebab_case(tmp_path):
    """save 文件名 sanitize 为 kebab-case。"""
    store = ExperienceStore(tmp_path / "exp")
    doc = ExperienceDocument(
        title="修复 SSE 思考渲染（流式）",
        scenario="s",
        root_cause="",
        solution="sol",
        evidence="",
        tags=[],
        source={},
    )
    filename = store.save(doc)
    assert filename.startswith("EXPERIENCE-")
    assert filename.endswith(".md")
    slug = filename[len("EXPERIENCE-YYYYMMDD-") : -3]  # noqa: E203
    # kebab-case: 仅小写字母数字和连字符
    assert all(c.islower() or c.isdigit() or c == "-" for c in slug)


def test_save_slug_truncate_50(tmp_path):
    """slug 截断 50 字符。"""
    store = ExperienceStore(tmp_path / "exp")
    long_title = "A" * 100
    doc = ExperienceDocument(
        title=long_title, scenario="s", root_cause="", solution="sol", evidence="", tags=[], source={}
    )
    filename = store.save(doc)
    # EXPERIENCE-YYYYMMDD-<slug>.md, slug ≤ 50
    slug = filename.split("-", 2)[2].removesuffix(".md")
    assert len(slug) <= 50


def test_save_path_traversal_sanitized(tmp_path):
    """含 ../ 的 slug 被 sanitize 为安全文件名，限定 experiences/ 内。"""
    store = ExperienceStore(tmp_path / "exp")
    doc = ExperienceDocument(
        title="../../../etc/passwd",
        scenario="s",
        root_cause="",
        solution="sol",
        evidence="",
        tags=[],
        source={},
    )
    filename = store.save(doc)
    # 文件应落在 experiences/ 目录内
    assert (tmp_path / "exp" / filename).exists()
    # 不含 ..
    assert ".." not in filename


def test_save_conflict_not_overwrite(tmp_path):
    """同日同 slug 冲突不覆盖，抛 FileExistsError。"""
    store = ExperienceStore(tmp_path / "exp")
    doc = ExperienceDocument(
        title="冲突测试", scenario="s", root_cause="", solution="sol", evidence="", tags=[], source={}
    )
    filename = store.save(doc)
    original_content = (tmp_path / "exp" / filename).read_text()
    # 再次保存同 title → 冲突
    with pytest.raises(FileExistsError, match="冲突"):
        store.save(doc)
    # 原文件内容不变
    assert (tmp_path / "exp" / filename).read_text() == original_content


def test_save_original_text_not_rewritten(tmp_path):
    """原文落盘，to_md 不改写/摘要/压缩。"""
    store = ExperienceStore(tmp_path / "exp")
    body_text = "## 原始正文\n\n这是AI提交的原始经验正文，不应被改写或压缩。"
    doc = ExperienceDocument(
        title="原文落盘测试",
        scenario="原始场景",
        root_cause="原始根因",
        solution="原始解法",
        evidence="原始证据",
        tags=["原始标签"],
        source={"origin": "ai"},
        body=body_text,
    )
    filename = store.save(doc)
    content = (tmp_path / "exp" / filename).read_text()
    assert body_text in content
    assert "原始正文" in content
    assert "不应被改写或压缩" in content


def test_save_creates_dir_if_not_exist(tmp_path):
    """目录不存在时自动创建。"""
    exp_dir = tmp_path / "nested" / "exp"
    assert not exp_dir.exists()
    store = ExperienceStore(exp_dir)
    doc = ExperienceDocument(
        title="自动建目录", scenario="s", root_cause="", solution="sol", evidence="", tags=[], source={}
    )
    filename = store.save(doc)
    assert (exp_dir / filename).exists()


# ── 7.4 ExperienceStore.list_active ──


def _make_doc(
    title: str = "测试经验",
    scenario: str = "场景",
    solution: str = "解法",
    status: str = "active",
    tags: list[str] | None = None,
    body: str = "",
) -> ExperienceDocument:
    return ExperienceDocument(
        title=title,
        scenario=scenario,
        root_cause="",
        solution=solution,
        evidence="",
        tags=tags or [],
        source={},
        status=status,
        body=body,
    )


def test_list_active_only_returns_active(tmp_path):
    """默认仅返回 status=active 经验。"""
    store = ExperienceStore(tmp_path / "exp")
    store.save(_make_doc(title="active-exp", status="active"))
    store.save(_make_doc(title="archived-exp", status="archived"))
    store.save(_make_doc(title="invalid-exp", status="invalid"))
    results = store.list_active()
    assert len(results) == 1
    assert results[0]["summary"] == "active-exp"


def test_list_active_keyword_match(tmp_path):
    """关键词匹配 title/scenario/solution/tags。"""
    store = ExperienceStore(tmp_path / "exp")
    store.save(_make_doc(title="sse-render-fix", tags=["web", "sse"]))
    store.save(_make_doc(title="config-load-opt", tags=["config"]))
    results = store.list_active(query="sse")
    assert len(results) == 1
    assert "sse" in results[0]["summary"]


def test_list_active_limit_truncation(tmp_path):
    """limit 截断返回不超过 limit 条。"""
    store = ExperienceStore(tmp_path / "exp")
    for i in range(5):
        store.save(_make_doc(title=f"exp-limit-{i}"))
    results = store.list_active(limit=2)
    assert len(results) == 2


def test_list_active_dir_not_exist_returns_empty(tmp_path):
    """目录不存在返回空列表，不报错。"""
    store = ExperienceStore(tmp_path / "nonexistent")
    results = store.list_active()
    assert results == []


def test_list_active_corrupt_file_skipped(tmp_path):
    """文件损坏/解析失败跳过，返回可读部分。"""
    exp_dir = tmp_path / "exp"
    exp_dir.mkdir()
    store = ExperienceStore(exp_dir)
    store.save(_make_doc(title="正常经验"))
    # 写入损坏文件
    (exp_dir / "EXPERIENCE-20260813-corrupt.md").write_text("not valid front matter", encoding="utf-8")
    results = store.list_active()
    # 损坏文件跳过，正常经验仍返回
    assert len(results) == 1
    assert results[0]["summary"] == "正常经验"


def test_list_active_record_structure(tmp_path):
    """返回记录含 kind/ts/id/summary/file/tags/source/status 字段。"""
    store = ExperienceStore(tmp_path / "exp")
    store.save(_make_doc(title="结构测试", tags=["t1"], body="正文"))
    results = store.list_active()
    rec = results[0]
    assert rec["kind"] == "experience"
    assert "ts" in rec
    assert "id" in rec
    assert rec["summary"] == "结构测试"
    assert "file" in rec
    assert rec["tags"] == ["t1"]
    assert rec["status"] == "active"


# ── 7.5 ExperienceStore.update_status ──


def test_update_status_transition(tmp_path):
    """状态流转 active→archived→invalid→active 正确，不删除文档。"""
    store = ExperienceStore(tmp_path / "exp")
    filename = store.save(_make_doc(title="状态流转测试", status="active"))
    exp_id = filename.removesuffix(".md")
    # active → archived
    assert store.update_status(exp_id, "archived") is True
    doc = store.get(exp_id)
    assert doc is not None
    assert doc.status == "archived"
    # archived → invalid
    assert store.update_status(exp_id, "invalid") is True
    doc = store.get(exp_id)
    assert doc is not None
    assert doc.status == "invalid"
    # invalid → active (restore)
    assert store.update_status(exp_id, "active") is True
    doc = store.get(exp_id)
    assert doc is not None
    assert doc.status == "active"


def test_update_status_refreshes_updated_at(tmp_path):
    """update_status 刷新 updated_at。"""
    store = ExperienceStore(tmp_path / "exp")
    filename = store.save(_make_doc(title="时间戳测试"))
    exp_id = filename.removesuffix(".md")
    original = store.get(exp_id)
    assert original is not None
    original_updated = original.updated_at
    assert store.update_status(exp_id, "archived") is True
    updated = store.get(exp_id)
    assert updated is not None
    assert updated.updated_at != original_updated


def test_update_status_does_not_delete(tmp_path):
    """update_status 不删除文档文件。"""
    store = ExperienceStore(tmp_path / "exp")
    filename = store.save(_make_doc(title="不删除测试"))
    exp_id = filename.removesuffix(".md")
    assert store.update_status(exp_id, "archived") is True
    assert (tmp_path / "exp" / filename).exists()


def test_update_status_not_found_returns_false(tmp_path):
    """经验不存在返回 False，不创建空条目。"""
    store = ExperienceStore(tmp_path / "exp")
    assert store.update_status("EXPERIENCE-20260813-nonexistent", "archived") is False
    assert not (tmp_path / "exp").exists() or not list((tmp_path / "exp").glob("*.md"))


def test_get_returns_none_for_nonexistent(tmp_path):
    """get 不存在返回 None。"""
    store = ExperienceStore(tmp_path / "exp")
    assert store.get("EXPERIENCE-20260813-nonexistent") is None


def test_get_returns_none_for_corrupt(tmp_path):
    """get 损坏文件返回 None。"""
    exp_dir = tmp_path / "exp"
    exp_dir.mkdir()
    (exp_dir / "EXPERIENCE-20260813-bad.md").write_text("corrupt", encoding="utf-8")
    store = ExperienceStore(exp_dir)
    assert store.get("EXPERIENCE-20260813-bad") is None


# ── 7.6 RecordSearcher._search_experience ──


def test_search_kind_experience_returns_records(tmp_path):
    """kind=experience 检索返回结构化经验记录。"""
    exp_dir = tmp_path / "exp"
    store = ExperienceStore(exp_dir)
    store.save(_make_doc(title="经验检索测试", tags=["search"]))
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=store)
    results = searcher.search(kind="experience", query="经验")
    assert len(results) == 1
    assert results[0]["kind"] == "experience"
    assert "经验检索测试" in results[0]["summary"]


def test_search_kind_all_includes_experience(tmp_path):
    """kind=all 时 experience 与既有 kind 并列返回，kind 区分不混淆。"""
    exp_dir = tmp_path / "exp"
    store = ExperienceStore(exp_dir)
    store.save(_make_doc(title="并列经验"))
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=store)
    results = searcher.search(kind="all", query="并列", limit=20)
    exp_results = [r for r in results if r["kind"] == "experience"]
    assert len(exp_results) == 1
    assert "并列经验" in exp_results[0]["summary"]


def test_search_experience_store_none_returns_empty(tmp_path):
    """experience_store=None 时 _search_experience 返回空。"""
    searcher = RecordSearcher(audit_dir=tmp_path / "audit")
    assert searcher.search(kind="experience") == []
    # kind=all 也不含 experience
    results = searcher.search(kind="all", limit=10)
    assert all(r["kind"] != "experience" for r in results)


def test_search_kind_experience_no_match_returns_empty(tmp_path):
    """检索无匹配如实返回空，不静默报错。"""
    store = ExperienceStore(tmp_path / "exp")
    store.save(_make_doc(title="某经验"))
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=store)
    results = searcher.search(kind="experience", query="不存在的关键词xyz")
    assert results == []


# ── 7.7 run_save_experience / run_refine_experience ──


def test_run_save_experience_success(tmp_path):
    """沉淀成功回执含文件名/路径。"""
    store = ExperienceStore(tmp_path / "exp")
    result = run_save_experience(
        store,
        title="成功沉淀经验",
        scenario="场景",
        solution="解法",
        root_cause="根因",
        evidence="证据",
        tags=["tag1"],
        source={"task": "P1-2"},
        body="正文",
    )
    assert result.startswith("[save_experience]")
    assert "已沉淀" in result
    assert "EXPERIENCE-" in result


def test_run_save_experience_missing_required(tmp_path):
    """必填字段缺失返回 [参数错误]，不写入。"""
    store = ExperienceStore(tmp_path / "exp")
    # 缺 title
    result = run_save_experience(store, title="", scenario="s", solution="sol")
    assert result.startswith("[参数错误]")
    assert "title" in result
    # 缺 scenario
    result = run_save_experience(store, title="t", scenario="", solution="sol")
    assert result.startswith("[参数错误]")
    assert "scenario" in result
    # 缺 solution
    result = run_save_experience(store, title="t", scenario="s", solution="")
    assert result.startswith("[参数错误]")
    assert "solution" in result
    # 确认未写入任何文件
    assert not (tmp_path / "exp").exists() or not list((tmp_path / "exp").glob("*.md"))


def test_run_save_experience_conflict(tmp_path):
    """文件名冲突返回冲突提示，不假装成功。"""
    store = ExperienceStore(tmp_path / "exp")
    run_save_experience(store, title="冲突经验", scenario="s", solution="sol")
    result = run_save_experience(store, title="冲突经验", scenario="s", solution="sol")
    assert "冲突" in result or "[save_experience]" not in result


def test_run_refine_experience_archive(tmp_path):
    """refine_experience archive 状态流转回执。"""
    store = ExperienceStore(tmp_path / "exp")
    filename = store.save(_make_doc(title="归档测试"))
    exp_id = filename.removesuffix(".md")
    result = run_refine_experience(store, experience_id=exp_id, action="archive")
    assert result.startswith("[refine_experience]")
    assert "archived" in result
    doc = store.get(exp_id)
    assert doc is not None
    assert doc.status == "archived"


def test_run_refine_experience_invalidate_and_restore(tmp_path):
    """refine_experience invalidate/restore 状态流转。"""
    store = ExperienceStore(tmp_path / "exp")
    filename = store.save(_make_doc(title="失效恢复测试"))
    exp_id = filename.removesuffix(".md")
    # invalidate
    result = run_refine_experience(store, experience_id=exp_id, action="invalidate")
    assert "invalid" in result
    doc = store.get(exp_id)
    assert doc is not None
    assert doc.status == "invalid"
    # restore
    result = run_refine_experience(store, experience_id=exp_id, action="restore")
    assert "active" in result
    doc = store.get(exp_id)
    assert doc is not None
    assert doc.status == "active"


def test_run_refine_experience_not_found(tmp_path):
    """经验不存在返回 [未找到]，不创建空条目。"""
    store = ExperienceStore(tmp_path / "exp")
    result = run_refine_experience(store, experience_id="EXPERIENCE-20260813-none", action="archive")
    assert result.startswith("[未找到]")


def test_run_refine_experience_invalid_action(tmp_path):
    """action 非法返回 [参数错误]。"""
    store = ExperienceStore(tmp_path / "exp")
    result = run_refine_experience(store, experience_id="some-id", action="bad_action")
    assert result.startswith("[参数错误]")
    assert "archive/invalidate/restore" in result
