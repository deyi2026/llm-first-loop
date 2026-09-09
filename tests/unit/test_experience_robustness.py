"""经验库健壮性回归测试：解析三态契约 + 存储隔离与诊断（tasks.md R1/R2 / design §2.1.3-9）.

组A = 可降级文档解析（宽容降级路径）；组B = 契约固化（唯一失败形态 ExperienceParseError）；
组C = 不可解析隔离（三态扫描 + 脱敏留痕 + 目录级防护 + 诊断 Outcome，R2）；
组G = 写路径形态稳定（round-trip 锁定，R2）；A5/A6 = 可降级文档检索行为（R2 补充）。
fixture 一律 tmp_path 内嵌样本构造，零依赖 experiences/ 生产目录，任意环境可重复；
差分 harness 为验证性测试，对生产目录做解析面收敛检查（目录缺失则跳过）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.experiences.document import ExperienceDocument, ExperienceParseError, _coerce_mapping
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.search import _VALID_KINDS, InvalidSearchKindError, RecordSearcher
from llm_loop.introspection.tools_status import _SEARCH_RECORDS_KIND_HINT, run_search_records

# 事故样本全文复刻（EXPERIENCE-20260902-task-startup-discipline.md 形态，内联 JSON source）
INCIDENT_MD = (
    "---\n"
    "title: 任务启动纪律：过去已完成的任务不重启，未完成任务启动前必须先问用户\n"
    "scenario: 会话恢复/新会话开始/每轮任务决策时，需要决定是否启动执行时。\n"
    "root_cause: 自动重启历史任务浪费资源、可能产生重复副作用（重复写入/通知/覆盖产物）。\n"
    "solution: 三条纪律：已完成的过去任务一律不重新启动；未完成任务启动前必须先征得用户同意。\n"
    'evidence: 用户原话（2026-09-02 会话）："就是过去的任务，已经做过的，不应该起"\n'
    "tags: [任务管理, 后台任务, 用户确认, 会话恢复, 行为纪律, 高影响动作]\n"
    'source: {"type": "user_feedback"}\n'
    "status: active\n"
    'created_at: "2026-09-02T20:02:56.123456+08:00"\n'
    'updated_at: "2026-09-02T20:02:56.123456+08:00"\n'
    "---\n"
    "## 纪律说明\n\n"
    "任何重跑历史任务的动作默认视为高影响动作，未经用户授权不执行。\n"
)


# ── 组 A：可降级文档解析（宽容降级路径） ──


def test_a1_inline_json_source():
    """A1 内联 JSON source → 降级 {"raw": 原值}，原值完整保留（spec 5.1.1-2a）."""
    doc = ExperienceDocument.from_md('---\ntitle: t\nsource: {"type": "user_feedback"}\n---\nbody')
    assert doc.source == {"raw": '{"type": "user_feedback"}'}


def test_a2_plain_scalar_source():
    """A2 纯标量与防御形态 source → {"raw": str(原值)}（spec 5.1.1-2b + design 决策表）."""
    doc = ExperienceDocument.from_md("---\ntitle: t\nsource: user_feedback\n---\n")
    assert doc.source == {"raw": "user_feedback"}
    # 解析器可达的 list 形态（source: [a, b]）防御降级
    doc_list = ExperienceDocument.from_md("---\ntitle: t\nsource: [a, b]\n---\n")
    assert doc_list.source == {"raw": str(["a", "b"])}
    # _parse_value 不可达产物的穷举防御分支（design §2.1.3-1 决策表 int/float/bool/None/tuple 行）
    assert _coerce_mapping(123, "source") == {"raw": "123"}
    assert _coerce_mapping(1.5, "source") == {"raw": "1.5"}
    assert _coerce_mapping(True, "source") == {"raw": "True"}
    assert _coerce_mapping(None, "source") == {"raw": "None"}
    assert _coerce_mapping(("a", "b"), "source") == {"raw": str(("a", "b"))}


@pytest.mark.parametrize(
    ("source_lines", "expected"),
    [
        ("source:\n  type: user_feedback\n", {"type": "user_feedback"}),
        ("source: {}\n", {}),
        ("", {}),
    ],
)
def test_a3_legal_forms_no_regression(source_lines: str, expected: dict):
    """A3 合法形态零回归：缩进块/{} /缺省均不触发降级（spec 5.1.1-2c/2d、1c）."""
    doc = ExperienceDocument.from_md(f"---\ntitle: t\n{source_lines}---\nbody")
    assert doc.source == expected


def test_a4_incident_sample_full_text():
    """A4 事故样本全文复刻 → 走降级不抛 ValueError，文档可正常构造（spec 5.1.1-3b）."""
    doc = ExperienceDocument.from_md(INCIDENT_MD)
    assert doc.source == {"raw": '{"type": "user_feedback"}'}
    assert doc.status == "active"
    assert doc.title.startswith("任务启动纪律")
    assert doc.tags == ["任务管理", "后台任务", "用户确认", "会话恢复", "行为纪律", "高影响动作"]


# ── 组 B：契约固化（唯一失败形态 ExperienceParseError） ──


@pytest.mark.parametrize(
    "fuzzy_md",
    [
        "title: t\n---\n正文",
        "---\ntitle: t\n正文",
        "---\ntitle: t\n  bad indent line\n---\n",
        "---\ntitle: t\nsource:\n bad nested\n---\n",
        "---\ntags: 123\n---\n",
        "",
        "---\n---\n",
    ],
)
def test_b1_fuzzy_samples_no_escape(fuzzy_md: str):
    """B1 模糊样本集：成功返回合法文档或抛 ExperienceParseError 二择一（spec 5.1.1-3a）."""
    try:
        doc = ExperienceDocument.from_md(fuzzy_md)
    except ExperienceParseError:
        return
    assert isinstance(doc.title, str)
    assert isinstance(doc.tags, list)
    assert isinstance(doc.source, dict)


def test_b2_translated_message_contains_original_type(monkeypatch):
    """B2 兜底转译消息含原始异常类型名与摘要，from exc 保留异常链（spec 5.1.1-3c）.

    解析器产出值均为 str/list/dict（全可迭代），公开路径下兜底不可达（防御性闭环，
    design §2.1.3-2）——注入未知异常验证转译契约本身；注：`tags: 123` 实际走
    list(str) 静默拆分成功路径，design L310 的 list(int)→TypeError 假设与解析器
    实际行为不符，tags 语义错乱属范围外（spec 1.4 职责边界 2）。
    """

    def _boom(_content: str) -> dict:
        raise ValueError("dictionary update sequence element #0 has length 1; 2 is required")

    monkeypatch.setattr("llm_loop.experiences.document._parse_front_matter", _boom)
    with pytest.raises(
        ExperienceParseError, match=r"经验文档解析失败\(ValueError\): .+has length 1"
    ) as exc_info:
        ExperienceDocument.from_md("---\ntitle: t\n---\n")
    assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.parametrize(
    "legal_md",
    [
        (
            "---\n"
            'title: "含:冒号标题"\n'
            "scenario: 场景\n"
            "root_cause: 根因\n"
            "solution: 解法\n"
            "evidence: 证据\n"
            "tags: [python, web]\n"
            "source:\n"
            "  session: s1\n"
            '  task: "P1-2"\n'
            "status: archived\n"
            'created_at: "2026-08-13T10:00:00+08:00"\n'
            'updated_at: "2026-08-13T10:30:00+08:00"\n'
            "---\n"
            "## 正文\n\n内容\n"
        ),
        "---\ntitle: t\ntags: [a]\nsource: {}\n---\n",
        "---\ntitle: 空源\ntags: []\n---\n正文",
    ],
)
def test_b3_legal_samples_field_identical(legal_md: str):
    """B3 合法样本逐字段一致性快照：降级路径不侵蚀合法路径（spec 5.1.1-4a）."""
    baseline = ExperienceDocument.from_md(legal_md)
    assert isinstance(baseline.source, dict)
    assert all(isinstance(t, str) for t in baseline.tags)
    restored = ExperienceDocument.from_md(baseline.to_md())
    assert restored.title == baseline.title
    assert restored.scenario == baseline.scenario
    assert restored.root_cause == baseline.root_cause
    assert restored.solution == baseline.solution
    assert restored.evidence == baseline.evidence
    assert restored.tags == baseline.tags
    assert restored.source == baseline.source
    assert restored.status == baseline.status
    assert restored.created_at == baseline.created_at
    assert restored.updated_at == baseline.updated_at
    assert restored.body == baseline.body


# ── 差分 harness：生产 experiences/ 目录解析面收敛（验证性测试） ──


def test_differential_harness_production_dir():
    """生产 experiences/ 全量必须可解析；非法格式由独立 fixture 保留覆盖.

    历史 incident 文档已经进入数据治理，不再把“生产里必须永久留一条坏文档”当契约。
    差分 harness 现在更严格：当前生产目录若有任何 ExperienceParseError 都直接报告文件名。
    """
    prod_dir = Path(__file__).resolve().parents[2] / "experiences"
    md_files = sorted(prod_dir.glob("EXPERIENCE-*.md")) if prod_dir.is_dir() else []
    if not md_files:
        pytest.skip("生产 experiences/ 目录不存在或为空，差分 harness 跳过")
    unparseable: list[str] = []
    for path in md_files:
        try:
            doc = ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
        except ExperienceParseError:
            unparseable.append(path.name)
            continue
        assert isinstance(doc.title, str)
        assert isinstance(doc.scenario, str)
        assert isinstance(doc.root_cause, str)
        assert isinstance(doc.solution, str)
        assert isinstance(doc.evidence, str)
        assert isinstance(doc.tags, list) and all(isinstance(t, str) for t in doc.tags)
        assert isinstance(doc.source, dict)
        assert isinstance(doc.status, str)
        assert isinstance(doc.created_at, str)
        assert isinstance(doc.updated_at, str)
        assert isinstance(doc.body, str)
        assert isinstance(doc.superseded_by, str)
        assert isinstance(doc.promoted_to_rule, str)
        assert isinstance(doc.last_verified_at, str)
    assert not unparseable, f"生产经验库仍有不可解析文档: {unparseable}"


# ── R2 测试辅助：tmp_path 内嵌样本（零依赖 experiences/ 生产目录） ──

GOOD_MD = (
    "---\n"
    "title: 正常经验A\n"
    "scenario: 场景描述\n"
    "root_cause: 根因\n"
    "solution: 解法\n"
    "evidence: 证据\n"
    "tags: [检索, 测试]\n"
    "source:\n"
    "  type: user_feedback\n"
    "status: active\n"
    "---\n"
    "正常正文"
)

DEGRADABLE_MD = (
    "---\n"
    "title: 可降级经验B\n"
    "scenario: 场景描述\n"
    "root_cause: 根因\n"
    "solution: 解法\n"
    "evidence: 证据\n"
    "tags: [检索]\n"
    'source: {"type": "user_feedback"}\n'
    "status: active\n"
    "---\n"
    "可降级正文"
)

BAD_MD = "---\ntitle: t\n  bad indent line\n---\n"


class _FailingEmbedder:
    """embed 必失败的假 embedder（触发 T5 语义检索降级回退路径）。"""

    def embed(self, text: str) -> list[float]:
        raise RuntimeError("embed service unavailable")


def _exp_dir(tmp_path: Path, files: dict[str, str]) -> Path:
    """在 tmp 下构造经验目录并写入文档集。"""
    exp_dir = tmp_path / "exp"
    exp_dir.mkdir(parents=True)
    for name, content in files.items():
        (exp_dir / name).write_text(content, encoding="utf-8")
    return exp_dir


# ── 组 C：不可解析隔离（R2 / tasks §2.6 / design §2.1.3-9） ──


def test_c1_unparseable_isolated_normal_returned(tmp_path):
    """C1 坏+正常共存：返回全部正常文档、无异常；不可解析文档不在结果（spec 5.2.1-1a）."""
    exp_dir = _exp_dir(
        tmp_path,
        {
            "EXPERIENCE-20260903-good.md": GOOD_MD,
            "EXPERIENCE-20260903-bad.md": BAD_MD,
        },
    )
    store = ExperienceStore(exp_dir)
    results = store.list_active("经验", 20)
    assert [r["id"] for r in results] == ["EXPERIENCE-20260903-good"]
    outcome = store.search_outcome("经验", 20)
    assert outcome.scanned_count == 2
    assert outcome.skipped_count == 1
    assert outcome.degraded_count == 0
    assert outcome.scan_error is None


def test_c2_all_bad_dir_empty_and_sanitized_trace(tmp_path, caplog, monkeypatch):
    """C2 全坏目录：空结果不崩、skipped==全部数、留痕全文不含 home 前缀（spec 5.2.1-1c/3c/4.3-2）.

    注入含 /Users/... 形态的 OSError 摘要验证脱敏；全坏（skipped 非零）与真实零命中
    （skipped==0）经诊断可区分。
    """
    exp_dir = _exp_dir(
        tmp_path,
        {
            "EXPERIENCE-20260903-b1.md": BAD_MD,
            "EXPERIENCE-20260903-b2.md": BAD_MD,
        },
    )

    def _boom(self, *args, **kwargs):
        raise OSError(f"open failed: {Path.home() / 'experiences' / 'secret.md'}")

    monkeypatch.setattr(Path, "read_text", _boom)
    store = ExperienceStore(exp_dir)
    with caplog.at_level(logging.WARNING, logger="llm_loop.experiences.store"):
        results = store.list_active()
    assert results == []
    diag = store.last_experience_diagnostics
    assert diag["scanned"] == 2
    assert diag["skipped"] == 2
    assert diag["skipped"] > 0  # 全坏 ≠ 真实零命中，诊断可辨
    traces = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(traces) == 2
    for rec in traces:
        msg = rec.getMessage()
        assert str(Path.home()) not in msg
        assert "/Users/" not in msg
        assert "secret.md" in msg  # 归因线索保留（脱敏后 ~ 形态）


def test_c3_trace_elements_per_skipped_doc(tmp_path, caplog):
    """C3 留痕要素：每跳过文档各 1 条含文件名+异常类型的 WARNING；正常/可降级零留痕（spec 5.2.1-3a、5.1.1-5a）."""
    exp_dir = _exp_dir(
        tmp_path,
        {
            "EXPERIENCE-20260903-good.md": GOOD_MD,
            "EXPERIENCE-20260903-deg.md": DEGRADABLE_MD,
            "EXPERIENCE-20260903-bad.md": BAD_MD,
        },
    )
    store = ExperienceStore(exp_dir)
    with caplog.at_level(logging.WARNING, logger="llm_loop.experiences.store"):
        store.list_active()
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1
    msg = warns[0].getMessage()
    assert "[经验库] 跳过不可解析文档" in msg
    assert "EXPERIENCE-20260903-bad.md" in msg
    assert "ExperienceParseError" in msg
    assert "EXPERIENCE-20260903-good.md" not in msg
    assert "EXPERIENCE-20260903-deg.md" not in msg


def test_c4_trace_best_effort(tmp_path, monkeypatch):
    """C4 留痕 best-effort：logger.warning 抛异常 → 检索照常返回正确结果（spec 5.2.1-3b、4.2-5）."""

    def _boom(*args, **kwargs):
        raise RuntimeError("logging handler fault")

    monkeypatch.setattr("llm_loop.experiences.store.logger.warning", _boom)
    exp_dir = _exp_dir(
        tmp_path,
        {
            "EXPERIENCE-20260903-good.md": GOOD_MD,
            "EXPERIENCE-20260903-bad.md": BAD_MD,
        },
    )
    store = ExperienceStore(exp_dir)
    results = store.list_active("经验", 20)
    assert [r["id"] for r in results] == ["EXPERIENCE-20260903-good"]


def test_c5_get_update_status_bad_doc_no_raise(tmp_path):
    """C5 get/update_status 坏文档分别返回 None/False，不上抛（spec 5.2.1-1 读取路径）."""
    exp_dir = _exp_dir(tmp_path, {"EXPERIENCE-20260903-bad.md": BAD_MD})
    store = ExperienceStore(exp_dir)
    assert store.get("EXPERIENCE-20260903-bad") is None
    assert store.update_status("EXPERIENCE-20260903-bad", "archived") is False


def test_c6_dir_level_scan_protection(tmp_path, monkeypatch):
    """C6 目录级扫描防护：glob 抛 PermissionError → 不崩、scan_error 非空且脱敏（spec 5.2.1-4a、4.2-4）."""
    exp_dir = _exp_dir(tmp_path, {"EXPERIENCE-20260903-good.md": GOOD_MD})

    def _glob_boom(self, pattern):
        raise PermissionError(13, f"cannot list: {Path.home() / 'secret-dir'}")

    monkeypatch.setattr(Path, "glob", _glob_boom)
    store = ExperienceStore(exp_dir)
    outcome = store.search_outcome()
    assert outcome.records == []
    assert outcome.scan_error is not None
    assert str(Path.home()) not in outcome.scan_error
    assert "/Users/" not in outcome.scan_error
    assert store.last_experience_diagnostics["scan_error"] is not None
    assert store.list_active() == []  # 兼容 wrapper 同样不崩


def test_c7_dir_not_exist_short_circuit(tmp_path):
    """C7 目录不存在短路：空结果、scan_error=None（spec 5.2.1-4b）."""
    store = ExperienceStore(tmp_path / "nonexistent")
    assert store.list_active() == []
    outcome = store.search_outcome()
    assert outcome.records == []
    assert outcome.scan_error is None
    assert outcome.scanned_count == 0
    assert outcome.skipped_count == 0
    assert outcome.degraded_count == 0


def test_c8_incomplete_library_annotation_conditional(tmp_path):
    """C8 库不完整标注：skipped>0 且命中时 degraded 含 [经验库降级]；无跳过时不出现（spec 5.2.1-5a）."""
    exp_dir = _exp_dir(
        tmp_path,
        {
            "EXPERIENCE-20260903-good.md": GOOD_MD,
            "EXPERIENCE-20260903-bad.md": BAD_MD,
        },
    )
    store = ExperienceStore(exp_dir)
    results = store.list_active("正常", 20)
    assert len(results) == 1
    assert "[经验库降级]" in results[0]["degraded"]
    assert "跳过 1 个不可解析文档" in results[0]["degraded"]
    exp_dir2 = _exp_dir(tmp_path / "2", {"EXPERIENCE-20260903-good.md": GOOD_MD})
    results2 = ExperienceStore(exp_dir2).list_active("正常", 20)
    assert len(results2) == 1
    assert "degraded" not in results2[0]


def test_c9_degraded_annotation_coexist(tmp_path):
    """C9 标注叠加共存：[语义检索降级] 与 [经验库降级] "；"拼接（spec 6.2-4、5.2.1-5）."""
    exp_dir = _exp_dir(
        tmp_path,
        {
            "EXPERIENCE-20260903-good.md": GOOD_MD,
            "EXPERIENCE-20260903-bad.md": BAD_MD,
        },
    )
    store = ExperienceStore(exp_dir, embedder=_FailingEmbedder())
    results = store.list_active("正常", 20)
    assert len(results) == 1
    text = results[0]["degraded"]
    assert "[语义检索降级]" in text
    assert "[经验库降级]" in text
    assert "；" in text
    assert text.index("[语义检索降级]") < text.index("[经验库降级]")


# ── 组 G：写路径形态稳定（R2 / tasks §2.5 / design §2.1.3-3，D15） ──


def test_g1_update_status_roundtrip_raw_stable(tmp_path):
    """G1 update_status round-trip：raw 形态恒定，无静默改写（spec 5.2.1-6a、6.1-4）."""
    exp_dir = _exp_dir(tmp_path, {})
    store = ExperienceStore(exp_dir)
    doc = ExperienceDocument(
        title="降级文档",
        scenario="s",
        root_cause="r",
        solution="sol",
        evidence="e",
        tags=["a"],
        source={"raw": '{"type": "user_feedback"}'},
    )
    filename = store.save(doc)
    exp_id = filename.removesuffix(".md")
    before = store.get(exp_id)
    assert before is not None
    assert before.source == {"raw": '{"type": "user_feedback"}'}
    assert store.update_status(exp_id, "archived") is True
    after = ExperienceStore(exp_dir).get(exp_id)
    assert after is not None
    assert after.status == "archived"
    assert after.source == {"raw": '{"type": "user_feedback"}'}


def test_g2_to_md_keeps_raw_indent_block():
    """G2 to_md 对降级字段产出 source: + raw: 缩进块（spec 5.2.1-6b）."""
    doc = ExperienceDocument(
        title="t",
        scenario="s",
        root_cause="r",
        solution="sol",
        evidence="e",
        tags=[],
        source={"raw": '{"type": "user_feedback"}'},
    )
    md = doc.to_md()
    assert "source:\n" in md
    assert '  raw: "{\\"type\\": \\"user_feedback\\"}"' in md


def test_g3_raw_value_with_newline_rejected():
    """G3 raw 值含换行 → to_md 抛 ValueError 拒绝写入（spec 5.2.1-6b、6.1-4，D15）."""
    doc = ExperienceDocument(
        title="t",
        scenario="s",
        root_cause="r",
        solution="sol",
        evidence="e",
        tags=[],
        source={"raw": "line1\nline2"},
    )
    with pytest.raises(ValueError, match="换行"):
        doc.to_md()


# ── 组 A 补充（R2）：可降级文档检索行为 ──


def test_a5_degradable_doc_zero_skip_trace(tmp_path, caplog):
    """A5 可降级文档零跳过留痕（spec 5.1.1-5a）."""
    exp_dir = _exp_dir(
        tmp_path,
        {
            "EXPERIENCE-20260903-deg.md": DEGRADABLE_MD,
            "EXPERIENCE-20260903-good.md": GOOD_MD,
        },
    )
    store = ExperienceStore(exp_dir)
    with caplog.at_level(logging.WARNING, logger="llm_loop.experiences.store"):
        results = store.list_active()
    assert [r for r in caplog.records if "跳过不可解析文档" in r.getMessage()] == []
    assert len(results) == 2
    diag = store.last_experience_diagnostics
    assert diag["skipped"] == 0
    assert diag["degraded"] == 1


def test_a6_degradable_doc_in_results_with_annotation(tmp_path):
    """A6 可降级文档出现在结果中：raw 形态 + degraded_fields + 既有字段齐全（spec 5.2.1-2a/2b、6.2-3）."""
    exp_dir = _exp_dir(tmp_path, {"EXPERIENCE-20260903-deg.md": DEGRADABLE_MD})
    store = ExperienceStore(exp_dir)
    results = store.list_active()
    assert len(results) == 1
    rec = results[0]
    assert rec["source"] == {"raw": '{"type": "user_feedback"}'}
    assert rec["degraded_fields"] == ["source"]
    for key in ("kind", "ts", "id", "summary", "file", "tags", "source", "status"):
        assert key in rec
    assert rec["kind"] == "experience"
    assert rec["id"] == "EXPERIENCE-20260903-deg"
    assert rec["file"] == "EXPERIENCE-20260903-deg.md"
    assert rec["summary"] == "可降级经验B"
    assert rec["status"] == "active"
    assert rec["tags"] == ["检索"]


# ── R3 组 D：typed 归因（tasks §3.6 / design §2.1.3-9）──


def test_d1_invalid_kind_param_error_with_synthetic_hint(tmp_path):
    """D1 非法 kind → FAILURE [参数错误] + hint 枚举；hint 与 _VALID_KINDS 同源（spec 5.4.1-1b）."""
    # typed 事实源：search() 对非法 kind 抛 InvalidSearchKindError（ValueError 子类，契约兼容）
    searcher = RecordSearcher(audit_dir=tmp_path / "audit")
    with pytest.raises(InvalidSearchKindError) as ei:
        searcher.search(kind="no_such_kind")
    assert isinstance(ei.value, ValueError)
    assert "experience" in str(ei.value)
    # 工具层归因：typed 异常 → [参数错误]，建议段枚举与 _VALID_KINDS 同源
    r = run_search_records(
        None, searcher.search, {"kind": "no_such_kind", "query": "x"}, lambda: ""
    )
    assert r.status.value == "failure"
    assert "[参数错误]" in r.content
    assert "kind 取值不合法" in r.content
    assert f"可选 {_SEARCH_RECORDS_KIND_HINT}。" in r.content
    # hint 同源断言：模块常量恒等于 sorted(_VALID_KINDS) 拼接（消除双清单漂移）
    assert "/".join(sorted(_VALID_KINDS)) == _SEARCH_RECORDS_KIND_HINT
    for must in ("experience", "episode", "all", "self_eval"):
        assert must in _SEARCH_RECORDS_KIND_HINT


def test_d2_internal_error_not_param_error(tmp_path):
    """D2 kind 合法 + 内部异常 → [内部错误] 非 [参数错误]（spec 5.4.1-1a、5.4.3-2）.

    覆盖 experience/all 双路径与执行期 ValueError（本次事故形态）：泛化 except
    在 typed 之后，执行期 ValueError 不再误报为 kind 参数错误。
    """
    calls: list[dict] = []

    def _boom(**kw):
        calls.append(kw)
        raise RuntimeError("experience index corrupted")

    for kind in ("experience", "all"):
        r = run_search_records(None, _boom, {"kind": kind, "query": "x"}, lambda: "")
        assert r.status.value == "failure"
        assert "[内部错误]" in r.content
        assert "[参数错误]" not in r.content
        assert "kind 取值不合法" not in r.content
    assert [c["kind"] for c in calls] == ["experience", "all"]

    def _value_boom(**_kw):
        raise ValueError("dictionary update sequence element #0 has length 1; 2 is required")

    r2 = run_search_records(None, _value_boom, {"kind": "experience", "query": "x"}, lambda: "")
    assert r2.status.value == "failure"
    assert "[内部错误]" in r2.content
    assert "[参数错误]" not in r2.content


def test_d3_internal_error_receipt_content():
    """D3 内部错误回执：含类型名与脱敏单行摘要、无堆栈无绝对路径、建议可行（spec 5.4.1-2a/2b、4.3-1）."""

    def _boom(**_kw):
        raise RuntimeError(
            f"db corrupt at {Path.home() / 'experiences' / 'x.md'}\nstack frame detail"
        )

    r = run_search_records(None, _boom, {"kind": "experience", "query": "x"}, lambda: "")
    assert r.status.value == "failure"
    assert "[内部错误]" in r.content
    assert "事实:" in r.content and "原因:" in r.content and "建议:" in r.content
    assert "RuntimeError" in r.content
    # 单行压缩 + home 前缀脱敏（无堆栈形态、无 /Users/ 绝对路径）
    assert "db corrupt at ~/experiences/x.md stack frame detail" in r.content
    assert "\nstack" not in r.content
    assert str(Path.home()) not in r.content
    assert "/Users/" not in r.content
    # 建议给出可行方向（更换其它 kind / 联系运维），不建议无效的相同 kind 重试
    assert "episode" in r.content
    assert "运维" in r.content


def test_d4_exception_not_swallowed_as_zero_result():
    """D4 异常不吞并：内部异常场景不出现"未找到匹配"成功文案（spec 5.4.1-3a）."""

    def _boom(**_kw):
        raise RuntimeError("boom")

    r = run_search_records(None, _boom, {"kind": "experience", "query": "x"}, lambda: "")
    assert r.status.value == "failure"
    assert "未找到匹配" not in r.content
    assert "不伪造结果" not in r.content


@pytest.mark.parametrize("bad_limit", ["abc", [], object()])
def test_d5_invalid_limit_param_error(bad_limit):
    """D5 limit 非法（"abc"/[]/不可转换对象）→ FAILURE [参数错误]，不逃逸（spec 5.4.1）."""
    calls: list[dict] = []

    def _spy(**kw):
        calls.append(kw)
        return []

    r = run_search_records(
        None, _spy, {"kind": "experience", "query": "x", "limit": bad_limit}, lambda: ""
    )
    assert r.status.value == "failure"
    assert "[参数错误]" in r.content
    assert "limit" in r.content
    assert calls == []  # 非法 limit 在参数校验段拦截，不进入检索执行


# ── R3 组 E：诊断回执与端到端（tasks §3.6 / design §2.1.3-9）──


def _r3_tool(exp_dir: Path) -> Any:
    """端到端检索工具：RecordSearcher.search 绑定方法（覆盖 __self__ 诊断读取路径）."""
    searcher = RecordSearcher(
        audit_dir=exp_dir.parent / "audit", experience_store=ExperienceStore(exp_dir)
    )
    return searcher.search


def test_e1_tri_state_zero_result_distinction(tmp_path, monkeypatch):
    """E1 三态区分：真实零命中既有文案 / 部分损坏零命中显式说明 / 扫描失败 FAILURE（spec 5.3.1-1a/1b/1c）."""
    clean = _exp_dir(tmp_path / "1", {"EXPERIENCE-20260903-good.md": GOOD_MD})
    r = run_search_records(
        None, _r3_tool(clean), {"kind": "experience", "query": "不存在的查询词"}, lambda: ""
    )
    assert r.status.value == "success"
    assert "未找到匹配" in r.content
    assert "[检索诊断]" not in r.content

    partial = _exp_dir(
        tmp_path / "2",
        {"EXPERIENCE-20260903-good.md": GOOD_MD, "EXPERIENCE-20260903-bad.md": BAD_MD},
    )
    r2 = run_search_records(
        None, _r3_tool(partial), {"kind": "experience", "query": "不存在的查询词"}, lambda: ""
    )
    assert r2.status.value == "success"
    assert "未找到匹配" not in r2.content
    assert "结果可能不完整" in r2.content
    assert "跳过不可解析文档 1 个" in r2.content
    assert "[检索诊断]" in r2.content

    broken = _exp_dir(tmp_path / "3", {"EXPERIENCE-20260903-good.md": GOOD_MD})

    def _glob_boom(self, pattern):
        raise PermissionError(13, "cannot list")

    monkeypatch.setattr(Path, "glob", _glob_boom)
    r3 = run_search_records(
        None, _r3_tool(broken), {"kind": "experience", "query": "x"}, lambda: ""
    )
    monkeypatch.undo()
    assert r3.status.value == "failure"
    assert "扫描失败" in r3.content
    assert "未找到匹配" not in r3.content


def test_e2_diagnostics_reach_receipt(tmp_path):
    """E2 诊断到达：可降级命中 + 不可解析跳过混合 → 回执同时含命中数/降级数/跳过数（spec 5.3.1-2a、5.4.1-4a）."""
    exp_dir = _exp_dir(
        tmp_path,
        {
            "EXPERIENCE-20260903-good.md": GOOD_MD,
            "EXPERIENCE-20260903-deg.md": DEGRADABLE_MD,
            "EXPERIENCE-20260903-bad.md": BAD_MD,
        },
    )
    r = run_search_records(
        None, _r3_tool(exp_dir), {"kind": "experience", "query": "经验"}, lambda: ""
    )
    assert r.status.value == "success"
    assert "[search_records] 命中 2 条" in r.content
    assert "[检索诊断] 命中 2 条；降级字段记录 1 条；跳过不可解析文档 1 个（库不完整）" in r.content


def test_e3_all_corrupt_not_disguised_zero_hit(tmp_path):
    """E3 全坏 ≠ 未命中：全部不可解析 → 含跳过计数与库不完整诊断，非"未找到匹配"式 SUCCESS（spec 5.3.1-3a）."""
    exp_dir = _exp_dir(
        tmp_path,
        {"EXPERIENCE-20260903-b1.md": BAD_MD, "EXPERIENCE-20260903-b2.md": BAD_MD},
    )
    r = run_search_records(
        None, _r3_tool(exp_dir), {"kind": "experience", "query": "x"}, lambda: ""
    )
    assert r.status.value == "success"
    assert "未找到匹配" not in r.content
    assert "跳过 2 个" in r.content
    assert "库不完整" in r.content
    assert "[检索诊断]" in r.content


def test_e4_field_level_degradation_reaches_receipt(tmp_path):
    """E4 字段级降级信息到达：存在降级记录 → 回执出现"降级字段记录 M 条"（spec 5.3.1-2b）."""
    exp_dir = _exp_dir(tmp_path, {"EXPERIENCE-20260903-deg.md": DEGRADABLE_MD})
    r = run_search_records(
        None, _r3_tool(exp_dir), {"kind": "experience", "query": "经验"}, lambda: ""
    )
    assert r.status.value == "success"
    assert "命中 1 条" in r.content
    assert "降级字段记录 1 条" in r.content
    assert "[检索诊断]" in r.content
    assert "跳过" not in r.content  # 零跳过 → 跳过要素不出现


def test_e5_healthy_state_no_noise(tmp_path):
    """E5 健康态无噪音：全正常库 → 回执形态与既有完全一致、无诊断段、命中数照常（spec 5.3.1-2c、4.5-4）."""
    exp_dir = _exp_dir(tmp_path, {"EXPERIENCE-20260903-good.md": GOOD_MD})
    r = run_search_records(
        None, _r3_tool(exp_dir), {"kind": "experience", "query": "经验", "limit": 5}, lambda: ""
    )
    assert r.status.value == "success"
    assert "[检索诊断]" not in r.content
    assert "降级" not in r.content
    assert "库不完整" not in r.content
    assert "[search_records] 命中 1 条" in r.content


def test_e6_episode_unaffected_by_corrupt_experience(tmp_path):
    """E6 episode 不受波及：坏文档在场/不在场，kind="episode" 回执一致（spec 5.6.1-6b、1.4-5）."""

    class _FakeEpisodeStore:
        def search(self, session_id, query="", limit=10):
            return [{"kind": "episode", "ts": "t1", "id": "e1", "summary": "ep hit"}]

    def _tool(exp_dir: Path) -> Any:
        return RecordSearcher(
            audit_dir=exp_dir.parent / "audit",
            experience_store=ExperienceStore(exp_dir),
            episode_store=_FakeEpisodeStore(),
        ).search

    dirty = _exp_dir(
        tmp_path / "1",
        {"EXPERIENCE-20260903-good.md": GOOD_MD, "EXPERIENCE-20260903-bad.md": BAD_MD},
    )
    clean = _exp_dir(tmp_path / "2", {"EXPERIENCE-20260903-good.md": GOOD_MD})
    r_dirty = run_search_records(
        None, _tool(dirty), {"kind": "episode", "query": "kw"}, lambda: "s1"
    )
    r_clean = run_search_records(
        None, _tool(clean), {"kind": "episode", "query": "kw"}, lambda: "s1"
    )
    assert r_dirty.status == r_clean.status == ToolResultStatus.SUCCESS
    assert r_dirty.content == r_clean.content
    assert "ep hit" in r_dirty.content
    assert "[检索诊断]" not in r_dirty.content  # 非经验库路径不携带诊断（零噪音）


def test_e7_all_path_diagnostics_reach_receipt(tmp_path):
    """E7 all 路径诊断到达：experience 分支 skipped/degraded 计数进入诊断段，独立于 results[:limit] 截断（spec 5.3.1-2a、1.2.3 口径）."""
    exp_dir = _exp_dir(
        tmp_path,
        {
            "EXPERIENCE-20260903-good.md": GOOD_MD,
            "EXPERIENCE-20260903-deg.md": DEGRADABLE_MD,
            "EXPERIENCE-20260903-bad.md": BAD_MD,
        },
    )
    r = run_search_records(None, _r3_tool(exp_dir), {"kind": "all", "query": "经验"}, lambda: "s1")
    assert r.status.value == "success"
    assert "[检索诊断]" in r.content
    assert "降级字段记录 1 条" in r.content
    assert "跳过不可解析文档 1 个（库不完整）" in r.content


# ── R4 组 F：双 fixture 端到端（tasks §4.3 / design §2.1.3-9，事故要素版本化资产）──

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "experience_search_robustness"
DEGRADABLE_FIXTURE = FIXTURES_DIR / "degradable-inline-source.md"
UNPARSEABLE_FIXTURE = FIXTURES_DIR / "unparseable-frontmatter.md"

# OPS-DATA-01 第 3 步定向改写规则（source 定向改写为缩进块，其余逐字不动）
_INLINE_SOURCE_LINE = 'source: {"type": "user_feedback"}\n'
_INDENT_SOURCE_BLOCK = "source:\n  type: user_feedback\n"


def _load_fixture(path: Path) -> str:
    """读取入 Git 的双 fixture 内容（事故等价资产的唯一版本化载体）。"""
    return path.read_text(encoding="utf-8")


def test_f1_degradable_fixture_in_results_with_annotation(tmp_path, caplog):
    """F1 degradable fixture 在结果中：raw 形态 + degraded_fields + 降级标注到达回执、零跳过留痕（spec 5.6.1-2a/2b）."""
    exp_dir = _exp_dir(
        tmp_path,
        {"EXPERIENCE-20260903-fixture-deg.md": _load_fixture(DEGRADABLE_FIXTURE)},
    )
    store = ExperienceStore(exp_dir)
    with caplog.at_level(logging.WARNING, logger="llm_loop.experiences.store"):
        results = store.list_active("任务启动", 20)
    assert len(results) == 1
    rec = results[0]
    assert rec["source"] == {"raw": '{"type": "user_feedback"}'}
    assert rec["degraded_fields"] == ["source"]
    assert [r for r in caplog.records if "跳过不可解析文档" in r.getMessage()] == []
    diag = store.last_experience_diagnostics
    assert diag["skipped"] == 0
    assert diag["degraded"] == 1
    # 端到端：kind=experience / kind=all 均命中，字段级降级标注到达模型可见回执
    for kind in ("experience", "all"):
        r = run_search_records(
            None, _r3_tool(exp_dir), {"kind": kind, "query": "任务启动"}, lambda: "s1"
        )
        assert r.status.value == "success"
        assert "命中 1 条" in r.content
        assert "降级字段记录 1 条" in r.content
        assert "任务启动纪律" in r.content


def test_f2_unparseable_fixture_absent_with_sanitized_trace(tmp_path, caplog):
    """F2 unparseable fixture 不在结果中：留痕存在且脱敏、库不完整标注出现（spec 5.6.1-3a/3b）."""
    unparseable_id = "EXPERIENCE-20260902-fixture-unparseable"
    exp_dir = _exp_dir(
        tmp_path,
        {
            f"{unparseable_id}.md": _load_fixture(UNPARSEABLE_FIXTURE),
            "EXPERIENCE-20260903-good.md": GOOD_MD,
        },
    )
    store = ExperienceStore(exp_dir)
    with caplog.at_level(logging.WARNING, logger="llm_loop.experiences.store"):
        results = store.list_active("正常", 20)
    assert [r["id"] for r in results] == ["EXPERIENCE-20260903-good"]
    traces = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(traces) == 1
    msg = traces[0].getMessage()
    assert f"{unparseable_id}.md" in msg
    assert "ExperienceParseError" in msg
    assert str(Path.home()) not in msg
    assert "/Users/" not in msg
    assert "[经验库降级]" in results[0]["degraded"]
    assert "跳过 1 个不可解析文档" in results[0]["degraded"]
    r = run_search_records(
        None, _r3_tool(exp_dir), {"kind": "experience", "query": "正常"}, lambda: ""
    )
    assert r.status.value == "success"
    assert "跳过不可解析文档 1 个（库不完整）" in r.content


def test_f3_mixed_fixtures_outcome_counts(tmp_path):
    """F3 混合场景 Outcome 计数：双 fixture + 正常文档 → 四要素计数与结果集分立正确（spec 5.6.1-1a/3a）."""
    exp_dir = _exp_dir(
        tmp_path,
        {
            "EXPERIENCE-20260903-good.md": GOOD_MD,
            "EXPERIENCE-20260903-fixture-deg.md": _load_fixture(DEGRADABLE_FIXTURE),
            "EXPERIENCE-20260902-fixture-unparseable.md": _load_fixture(UNPARSEABLE_FIXTURE),
        },
    )
    outcome = ExperienceStore(exp_dir).search_outcome("", 20)
    assert outcome.scanned_count == 3
    assert outcome.degraded_count == 1
    assert outcome.skipped_count == 1
    assert outcome.scan_error is None
    ids = {r["id"] for r in outcome.records}
    assert ids == {"EXPERIENCE-20260903-good", "EXPERIENCE-20260903-fixture-deg"}
    by_id = {r["id"]: r for r in outcome.records}
    assert by_id["EXPERIENCE-20260903-fixture-deg"]["degraded_fields"] == ["source"]
    assert "degraded_fields" not in by_id["EXPERIENCE-20260903-good"]
    assert "[经验库降级]" in by_id["EXPERIENCE-20260903-good"]["degraded"]


# ── R4 组 H：OPS 订正验证与事故等价性（tasks §4.3 / design §2.1.3-9）──


def test_h1_ops_corrected_form_parses_normal_mapping():
    """H1 OPS 订正后形态解析：缩进块版 fixture → 正常映射（非 raw 降级形态）（spec 5.5.1-2b/2c）."""
    corrected = _load_fixture(DEGRADABLE_FIXTURE).replace(_INLINE_SOURCE_LINE, _INDENT_SOURCE_BLOCK)
    assert _INDENT_SOURCE_BLOCK in corrected  # 改写生效防呆（fixture 漂移即红灯）
    doc = ExperienceDocument.from_md(corrected)
    assert doc.source == {"type": "user_feedback"}
    assert doc.source != {"raw": '{"type": "user_feedback"}'}


def test_h2_post_correction_search_recovered(tmp_path, caplog):
    """H2 修复后检索恢复：缩进块版 fixture 命中、无降级标注、无留痕（spec 5.5.1-3a/3b）."""
    corrected = _load_fixture(DEGRADABLE_FIXTURE).replace(_INLINE_SOURCE_LINE, _INDENT_SOURCE_BLOCK)
    exp_dir = _exp_dir(
        tmp_path,
        {"EXPERIENCE-20260903-fixture-deg.md": corrected},
    )
    store = ExperienceStore(exp_dir)
    with caplog.at_level(logging.WARNING, logger="llm_loop.experiences.store"):
        results = store.list_active("任务启动", 20)
    assert len(results) == 1
    rec = results[0]
    assert rec["source"] == {"type": "user_feedback"}
    assert "degraded_fields" not in rec
    assert "degraded" not in rec
    assert caplog.records == []
    diag = store.last_experience_diagnostics
    assert diag["degraded"] == 0
    assert diag["skipped"] == 0


def test_h3_fixture_equivalence_with_production_incident_docs():
    """H3 fixture 保留坏格式证明；已治理的生产事故文档必须可解析.

    degradable fixture 继续覆盖 source raw 降级；unparseable fixture 继续证明非法 envelope
    会抛 ExperienceParseError。生产 incident 文档属于真实数据治理对象，一旦修复就不应为了
    维持历史红灯而重新破坏；当前存在的对应文档应能完整解析。
    """
    deg_doc = ExperienceDocument.from_md(_load_fixture(DEGRADABLE_FIXTURE))
    assert deg_doc.source == {"raw": '{"type": "user_feedback"}'}
    with pytest.raises(ExperienceParseError):
        ExperienceDocument.from_md(_load_fixture(UNPARSEABLE_FIXTURE))

    prod_dir = Path(__file__).resolve().parents[2] / "experiences"
    if not prod_dir.is_dir():
        pytest.skip("生产 experiences/ 目录不存在，生产侧等价性段跳过")
    incident = prod_dir / "EXPERIENCE-20260902-task-startup-discipline.md"
    if incident.exists():
        inc_doc = ExperienceDocument.from_md(incident.read_text(encoding="utf-8"))
        assert inc_doc.source in (
            {"raw": '{"type": "user_feedback"}'},
            {"type": "user_feedback"},
        )
    repaired_prods = [
        *sorted(prod_dir.glob("EXPERIENCE-20260829-err1210-*.md")),
        *sorted(prod_dir.glob("EXPERIENCE-20260902-task-restart-*.md")),
    ]
    if not repaired_prods:
        pytest.skip("生产 incident 文档不存在，生产侧治理段跳过")
    for path in repaired_prods:
        repaired = ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
        assert repaired.title
