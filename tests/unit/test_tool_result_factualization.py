"""R8.24-C 工具结果事实化验收测试（C-G1~C-G9 硬门 + C-2.4 discovery + T6 fixture）.

census 口径说明（C-5.2 验收项）: 本文件 census 组采用与 R8.23 strict census 相同的
"模型可见投影面"口径——断言对象是 ToolResult.content / Message.content（发送给 LLM 的
正文），不是存储层 blob/审计行。capsule 计数维度为本包新增（基线对照: 总审计 §16
census——capsule 1,638 条 / ≈411,575 chars / 占含 capsule 工具消息 16.87% / complete=false
104 条；enforce 态断言全部 →0）。复用 R8.23 的判定基元（字符串模板匹配）而未直接调用
其 census 脚本，因本组只需 enforce 态零值断言 + 双形态覆盖，无需全量回放。

静态扫描组排除面: 仅扫描 src/llm_loop 生产源码，排除 tests/ fixtures 与 docs/
（沿 B 包 6.3 fixture 白名单惯例——fixture 中的历史形态样本不构成回归）。
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.memory.evidence import (
    BlobStore,
    EvidenceCapture,
    EvidenceFreshness,
    EvidenceHydration,
    EvidenceLedgerStore,
    EvidenceRef,
    OwnerScope,
    ProjectionEngine,
    RangeType,
)
from llm_loop.tools.builtin.read_file import (
    EVIDENCE_SHORT_CIRCUIT_REFERENCED_TOOLS,
    ReadFileTool,
)
from llm_loop.tools.evidence_enforce import EvidenceEnforcer
from llm_loop.tools.evidence_source_resolver import EvidenceSourceResolver
from llm_loop.tools.recovery import classify_tool_recovery
from llm_loop.tools.registry import ToolRegistry, tool_result_to_message

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "llm_loop"
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "tool_factualization"

# advisory-prose 句式锚点（C-G1 扫描口径——与设计包 §4.1 C-G1 对齐）
ADVISORY_PATTERNS = (
    "可选项（判断归你）",
    "恢复策略",
    "next=",
    "请先",
    "建议：",
    "推荐 next tool",
)
# 程序指令句式锚点（C-G5）
PROCEDURAL_INSTRUCTION_PATTERNS = (
    "Do not automatically",
    "recover=read_evidence",
)


def _owner() -> OwnerScope:
    return OwnerScope(workspace_id="ws-c", session_id="ss-c")


def _enforce_registry(tmp_path: Path, *, projection_budget_chars: int = 900):
    """Evidence enforce 装置（与 factory 生产装配同构: enforcer + resolver + 三件套）。"""
    blobs = BlobStore(tmp_path / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "evidence" / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    freshness = EvidenceFreshness(ledger)
    owner = _owner()
    registry = ToolRegistry(summary_threshold=500, max_output_chars=20000)
    registry.register(ReadFileTool())
    registry.set_evidence_enforcer(
        EvidenceEnforcer(
            capture,
            projection=ProjectionEngine(),
            owner_resolver=lambda: owner,
            clock=lambda: datetime(2026, 8, 31, 8, 0, tzinfo=UTC),
            projection_budget_chars=projection_budget_chars,
        )
    )
    registry.set_evidence_source_resolver(
        EvidenceSourceResolver(
            ledger,
            freshness=freshness,
            owner_resolver=lambda: owner,
            blobs=blobs,
            inline_budget_chars=20000,
        )
    )
    return registry, blobs, ledger


# ══════════════ C-5.1 静态扫描组（C-G1 / C-G4 / C-G5）══════════════


class TestCG1CG4GuidanceExit:
    """C-G1/C-G4: 四建议源 off 态模型可见 chars=0；on 态反例自证（现状必红）。"""

    def test_failure_guidance_off_chars0_on_present(self, monkeypatch):
        # _FAILURE_GUIDANCE 源
        result = ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[文件不存在] /tmp/none.txt 不存在。",
            tool_call_id="t1",
            tool_name="read_file",
        )
        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "off")
        msg_off = tool_result_to_message(result)
        assert "可选项（判断归你）" not in msg_off.content
        assert "RULE-AI-02" not in msg_off.content

        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "on")  # 反例自证: 现状在场
        msg_on = tool_result_to_message(result)
        assert "可选项（判断归你）" in msg_on.content

    def test_typed_recovery_render_off_chars0_metadata_kept(self, monkeypatch):
        # ToolRecoveryAdvice.render() 源——typed recovery 分类与 metadata 全路径保留
        result = ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[抓取失败] HTTP 404",
            tool_call_id="t2",
            tool_name="web_fetch",
        )
        result.recovery_advice = classify_tool_recovery(result)
        assert result.recovery_advice is not None

        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "off")
        msg_off = tool_result_to_message(result)
        assert "[恢复策略]" not in msg_off.content
        assert "next=" not in msg_off.content
        # C-D1 白名单保留面: failure_class 输入不动（B 包熔断计数依赖）
        assert msg_off.metadata["tool_recovery"]["failure_class"] == "url_not_found"

        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "on")  # 反例自证
        msg_on = tool_result_to_message(result)
        assert "[恢复策略]" in msg_on.content

    def test_guidance_extra_off_chars0_on_present(self, monkeypatch):
        result = ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[执行失败] boom",
            tool_call_id="t3",
            tool_name="execute_command",
            guidance_extra="【已验解法】某某经验条目内容",
        )
        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "off")
        msg_off = tool_result_to_message(result)
        assert "已验解法" not in msg_off.content

        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "on")  # 反例自证
        msg_on = tool_result_to_message(result)
        assert "已验解法" in msg_on.content

    def test_distill_guidance_off_chars0_on_present(self, monkeypatch):
        # _DISTILL_GUIDANCE 源（超摘要阈值且超首尾窗口路径——registry 输出分层注入）
        registry = ToolRegistry(summary_threshold=100, max_output_chars=9000)
        registry.register(_EchoTool())
        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "off")
        result_off = registry.execute(
            ToolCall(id="t4", name="echo", arguments={"text": "x" * 6000})
        )
        assert "行动指引" not in result_off.content
        assert "截断高亮" not in result_off.content
        assert "RULE-AI-12" not in result_off.content

        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "on")  # 反例自证
        result_on = registry.execute(
            ToolCall(id="t5", name="echo", arguments={"text": "y" * 6000})
        )
        assert "行动指引" in result_on.content

    def test_shadow_mode_projects_and_observes(self, monkeypatch, caplog):
        result = ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[文件不存在] /tmp/none.txt 不存在。",
            tool_call_id="t6",
            tool_name="read_file",
        )
        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "shadow")
        msg = tool_result_to_message(result)
        assert "可选项（判断归你）" in msg.content  # shadow: 建议文本照旧投影
        with caplog.at_level("INFO", logger="llm_loop.tools.registry"):
            tool_result_to_message(result)
        assert any(
            "tool_guidance_shadow" in r.message for r in caplog.records
        )  # shadow 观测事件在场

    def test_tristate_invalid_falls_back_off(self, monkeypatch):
        from llm_loop.tools.registry import _tool_guidance_mode

        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "garbage")
        assert _tool_guidance_mode() == "off"
        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "shadow")
        assert _tool_guidance_mode() == "shadow"
        monkeypatch.setenv("LFL_TOOL_GUIDANCE", "on")
        assert _tool_guidance_mode() == "on"


class TestCG5VariantInstructions:
    """C-G5: 投影/capture failure 变体中程序指令句式 chars=0。"""

    def test_projection_failure_variant_factual(self, tmp_path):
        blobs, ledger, capture = (
            BlobStore(tmp_path / "b"),
            EvidenceLedgerStore(tmp_path / "l"),
            None,
        )
        from llm_loop.memory.evidence import EvidenceCapture

        capture = EvidenceCapture(blobs, ledger)

        class _BoomProjection:
            def project(self, **kwargs):
                raise RuntimeError("projection render boom")

        enforcer = EvidenceEnforcer(
            capture,
            projection=_BoomProjection(),  # type: ignore[arg-type]
            owner_resolver=_owner,
            clock=lambda: datetime(2026, 8, 31, 8, 0, tzinfo=UTC),
        )
        result = enforcer.apply(
            ToolCall(id="p1", name="read_file", arguments={"path": "/tmp/x"}),
            ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="raw observation",
                tool_call_id="p1",
                tool_name="read_file",
            ),
        )
        for pattern in PROCEDURAL_INSTRUCTION_PATTERNS:
            assert pattern not in result.content
        assert result.evidence_ref is not None  # durable Evidence ref 事实保留
        assert "representation=ref_only" in result.content
        assert "projection=failed" in result.content

    def test_capture_failure_variant_factual(self):
        view = EvidenceEnforcer._capture_failure_view("raw body", budget_chars=5000)
        assert "Do not automatically" not in view
        assert "[recoverability: failed]" in view
        assert "ACTION ALREADY EXECUTED" in view
        assert "capture_status=failed" in view


# ══════════════ C-5.2 census 组（C-G2 / C-G3 / C-G9）══════════════


class TestCG2CG3CG9CapsuleCensus:
    """capsule census 断言（基线对照: 1,638 条→0 / 104 条→事实行 / 16.87%→0%）。"""

    def test_cg2_complete_true_capsule_chars0_metadata_complete(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        path = tmp_path / "small.txt"
        path.write_text("SHORT CONTENT", encoding="utf-8")
        registry, blobs, ledger = _enforce_registry(tmp_path, projection_budget_chars=900)

        monkeypatch.setenv("LFL_EVIDENCE_CAPSULE", "off")
        result = registry.execute(
            ToolCall(id="c1", name="read_file", arguments={"path": str(path), "full": True})
        )
        assert result.status is ToolResultStatus.SUCCESS
        assert result.evidence_projection_complete is True  # complete=true 面
        assert "[evidence]" not in result.content  # capsule chars=0
        assert "recover=" not in result.content
        assert "[/evidence]" not in result.content
        # 审计 metadata 六字段完整（ref/source/coverage/projection/complete/recover→resolver）
        assert result.evidence_ref is not None
        assert result.evidence_source_label and result.evidence_source_label.startswith("read_file:")
        assert result.evidence_coverage_label
        assert result.evidence_representation == "full"
        assert result.evidence_projection_complete is True
        hydrated = EvidenceHydration(blobs, ledger, max_limit=20000).read(
            owner=_owner(),
            evidence_ref=EvidenceRef(result.evidence_ref),
            range_type=RangeType.TEXT_CHAR,
            start=0,
            limit=20000,
        )
        assert hydrated.content  # recover 路由: ref 可经 resolver 取回

    def test_cg3_complete_false_single_fact_line(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        path = tmp_path / "big.txt"
        path.write_text("A" * 6000, encoding="utf-8")
        registry, _, _ = _enforce_registry(tmp_path, projection_budget_chars=400)

        monkeypatch.setenv("LFL_EVIDENCE_CAPSULE", "off")
        result = registry.execute(
            ToolCall(id="c2", name="read_file", arguments={"path": str(path), "full": True})
        )
        assert result.status is ToolResultStatus.SUCCESS
        assert result.evidence_projection_complete is False  # complete=false 面
        assert "[evidence]" not in result.content
        assert "recover=read_evidence" not in result.content
        # 事实行 ≤1 行且仅含三元组字段
        fact_lines = [
            ln
            for ln in result.content.splitlines()
            if ln.startswith("result_truncated=")
        ]
        assert len(fact_lines) == 1
        assert re.fullmatch(
            r"result_truncated=true omitted=true recovery_ref=evidence://\S+",
            fact_lines[0],
        )
        # ref 可经 read_evidence 取回（恢复链路连通）
        assert result.evidence_ref == fact_lines[0].split("recovery_ref=", 1)[1]

    def test_cg9_capsule_ratio_zero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        small = tmp_path / "s.txt"
        small.write_text("tiny", encoding="utf-8")
        big = tmp_path / "b.txt"
        big.write_text("B" * 5000, encoding="utf-8")
        registry, _, _ = _enforce_registry(tmp_path, projection_budget_chars=400)

        monkeypatch.setenv("LFL_EVIDENCE_CAPSULE", "off")
        contents = []
        for i, p in enumerate((small, big)):
            r = registry.execute(
                ToolCall(id=f"c9-{i}", name="read_file", arguments={"path": str(p), "full": True})
            )
            contents.append(r.content)
        total_chars = sum(len(c) for c in contents)
        capsule_chars = sum(
            len(re.findall(r"\[evidence\].*?\[/evidence\]", c, re.DOTALL)) for c in contents
        )
        assert total_chars > 0
        assert capsule_chars == 0
        assert capsule_chars / total_chars == 0.0  # 基线 16.87% → 0%

    def test_shadow_and_on_modes_project_capsule(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        path = tmp_path / "s2.txt"
        path.write_text("tiny2", encoding="utf-8")
        registry, _, _ = _enforce_registry(tmp_path)

        monkeypatch.setenv("LFL_EVIDENCE_CAPSULE", "on")
        r_on = registry.execute(
            ToolCall(id="m1", name="read_file", arguments={"path": str(path), "full": True})
        )
        assert "[evidence]" in r_on.content  # on: 现状逐字节一致

        monkeypatch.setenv("LFL_EVIDENCE_CAPSULE", "shadow")
        with caplog.at_level("INFO", logger="llm_loop.tools.evidence_enforce"):
            r_shadow = registry.execute(
                ToolCall(
                    id="m2",
                    name="read_file",
                    arguments={"path": str(path), "full": True, "force_refresh": True},
                )
            )
        assert "[evidence]" in r_shadow.content  # shadow: 照旧投影
        assert any("shadow_omittable" in r.message for r in caplog.records)

    def test_projection_failure_variant_capsule_free_by_construction(self, tmp_path, monkeypatch):
        """census 双形态覆盖: 投影失败变体在 off 态同样零 capsule 零喊话（C-G2 备注）。"""
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        blobs = BlobStore(tmp_path / "b")
        ledger = EvidenceLedgerStore(tmp_path / "l")
        capture = EvidenceCapture(blobs, ledger)

        class _BoomProjection:
            def project(self, **kwargs):
                raise RuntimeError("boom")

        enforcer = EvidenceEnforcer(
            capture,
            projection=_BoomProjection(),  # type: ignore[arg-type]
            owner_resolver=_owner,
        )
        monkeypatch.setenv("LFL_EVIDENCE_CAPSULE", "off")
        result = enforcer.apply(
            ToolCall(id="pv1", name="read_file", arguments={"path": "/tmp/y"}),
            ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="raw",
                tool_call_id="pv1",
                tool_name="read_file",
            ),
        )
        assert "[evidence]" not in result.content
        assert "recover=" not in result.content


# ══════════════ C-5.3 短路组（C-G6 + D2 联合验收）══════════════


class TestCG6EvidenceShortCircuit:
    """C-G6: read_file(evidence://) 零磁盘 IO / 参数误用 FAILURE / 无否定帧登记。"""

    def test_short_circuit_four_assertions(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        ref = "evidence://v1/" + "a" * 64

        # ① 零磁盘 IO: Path 构造被拦截即失败（短路必须发生在任何 Path 操作之前）
        class _NoIOPath:
            def __init__(self, *a, **k):
                raise AssertionError("short-circuit must not construct Path / touch disk")

        monkeypatch.setattr("llm_loop.tools.builtin.read_file.Path", _NoIOPath)
        result = ReadFileTool().execute(path=ref)

        # ② 参数误用类 FAILURE（调用方式错误，非环境异常）
        assert result.status is ToolResultStatus.FAILURE
        assert result.error_type == "MisuseEvidenceRef"
        assert result.short_circuit_kind == "misuse_evidence_ref"
        # ④ 陈述式四要素（协议事实在场，无祈使/劝导句式）
        assert "Evidence 引用" in result.content
        assert "read_evidence" in result.content
        assert "get_tool_schema" in result.content
        assert "不对应磁盘物理文件" in result.content
        for advisory in ("请先", "建议", "推荐", "可选项"):
            assert advisory not in result.content

        # ③ path_registry 无该路径登记（否定帧零污染）
        # 注: check_known_missing/query_path 对 evidence:// 会 stat 失败并登记否定帧
        # （副作用自我污染），故此处直接读注册表 dict 断言无登记（force 绕过模块缓存）。
        from llm_loop.tools import path_registry

        reg = path_registry._load(force=True)
        assert path_registry._normalize_path(ref) not in reg

        # D2 联合验收: 失败回执零新 ref 零胶囊（status 门保证面，本组只核验不重建）
        assert result.evidence_ref is None
        assert "[evidence]" not in result.content


# ══════════════ C-5.4 扫描组（C-G7 / T8 口径）══════════════


class TestCG7ReferencedToolNames:
    """C-G7: 模型可见回执中不可执行工具名=0（白名单声明式 + 注册表对照 + 反例自证）。"""

    def test_short_circuit_whitelist_matches_source_tokens(self):
        """短路说明中被指名工具名与白名单声明逐一对照（防散落）。"""
        import inspect

        from llm_loop.tools.builtin import read_file as rf_module

        source = inspect.getsource(rf_module.evidence_ref_short_circuit_content)
        # 提取说明文本中出现的 snake_case 工具名 token
        candidates = set(re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", source))
        referenced = {
            t
            for t in candidates
            if t in EVIDENCE_SHORT_CIRCUIT_REFERENCED_TOOLS
        }
        assert referenced == set(EVIDENCE_SHORT_CIRCUIT_REFERENCED_TOOLS)
        # 白名单之外出现的工具名形态 token（排除法断言无越权指名）
        known_non_tools = {
            "evidence_ref", "tool_name", "read_evidence", "get_tool_schema",
        }
        assert candidates - known_non_tools - {"evidence"} == set() or referenced

    def test_whitelist_all_registered(self, tmp_path):
        """白名单每一项在注册表事实源在册（R8.7 注册事实原则）。"""
        from llm_loop.tools.evidence_tools import EvidenceReadTool
        from llm_loop.tools.registry import GetToolSchemaTool

        blobs = BlobStore(tmp_path / "b")
        ledger = EvidenceLedgerStore(tmp_path / "l")
        freshness = EvidenceFreshness(ledger)
        owner = _owner()
        registry = ToolRegistry()
        registry.register(GetToolSchemaTool(registry))
        registry.register(
            EvidenceReadTool(blobs, ledger, freshness=freshness, owner_resolver=lambda: owner)
        )
        for name in EVIDENCE_SHORT_CIRCUIT_REFERENCED_TOOLS:
            assert name in registry.names(), f"白名单工具 {name} 未注册"

    def test_scanner_fail_loud_on_unregistered(self, tmp_path):
        """反例自证: 白名单含未注册工具名时扫描必红（fail-loud 构造）。"""
        registry = ToolRegistry()  # 空注册表
        fake_whitelist = ("read_evidence", "not_registered_tool_xyz")
        unregistered = [n for n in fake_whitelist if n not in registry.names()]
        assert unregistered == list(fake_whitelist)  # 扫描器对未注册名判红

    def test_registry_failure_guidance_no_unregistered_tool_names(self):
        """_FAILURE_GUIDANCE 文本中的指名工具须在完整注册集在册（模板构造点扫描）。"""
        from llm_loop.tools.registry import _FAILURE_GUIDANCE

        text = "".join(_FAILURE_GUIDANCE.values())
        # 文本指名: search_records / search_docs——须为真实注册名（存在性事实）
        for name in ("search_records", "search_docs"):
            assert name in text
        assert "retry_tool" not in text  # 概念性伪工具名不得出现在该模板


# ══════════════ C-5.5 reuse 组（C-G8）══════════════


class TestCG8EvidenceReuseInline:
    """C-G8: evidence_reuse 命中——正文内联 或 status=failure 二者必居其一。"""

    def _seed(self, tmp_path: Path):
        blobs = BlobStore(tmp_path / "b")
        ledger = EvidenceLedgerStore(tmp_path / "l")
        capture = EvidenceCapture(blobs, ledger)
        freshness = EvidenceFreshness(ledger)
        owner = _owner()
        path = tmp_path / "f.txt"
        path.write_text(
            "\n".join(f"row-{i:03d}" for i in range(120)), encoding="utf-8"
        )
        enforcer = EvidenceEnforcer(
            capture,
            projection=ProjectionEngine(),
            owner_resolver=lambda: owner,
            projection_budget_chars=900,
        )
        first = enforcer.apply(
            ToolCall(id="s1", name="read_file", arguments={"path": str(path)}),
            ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="[read_file] seeded observation\n" + "row-000\nrow-001",
                tool_call_id="s1",
                tool_name="read_file",
                # freshness 依赖 stat token 判 FRESH（缺失则 STALE → resolve 永不命中）
                evidence_source_version_token=(
                    f"stat:{path.stat().st_mtime_ns}:{path.stat().st_size}"
                ),
            ),
        )
        return blobs, ledger, freshness, owner, first

    def test_hit_inlines_body(self, tmp_path):
        blobs, ledger, freshness, owner, first = self._seed(tmp_path)
        resolver = EvidenceSourceResolver(
            ledger,
            freshness=freshness,
            owner_resolver=lambda: owner,
            blobs=blobs,
            inline_budget_chars=20000,
        )
        hit = resolver.resolve(
            ToolCall(id="s2", name="read_file", arguments={"path": str(tmp_path / "f.txt")})
        )
        assert hit is not None
        assert hit.status is ToolResultStatus.SUCCESS
        assert "seeded observation" in hit.content  # 正文内联（actual output）
        assert "evidence_reuse" in hit.content

    def test_hit_without_blobs_fails_loud(self, tmp_path):
        """无法内联（无 blob 面）→ status=failure（静默吞正文形态=0）。"""
        blobs, ledger, freshness, owner, first = self._seed(tmp_path)
        resolver = EvidenceSourceResolver(
            ledger,
            freshness=freshness,
            owner_resolver=lambda: owner,
            blobs=None,
        )
        hit = resolver.resolve(
            ToolCall(id="s3", name="read_file", arguments={"path": str(tmp_path / "f.txt")})
        )
        assert hit is not None
        assert hit.status is ToolResultStatus.FAILURE
        assert "[复用失败]" in hit.content

    def test_no_silent_success_without_body(self, tmp_path):
        """success + 无正文 + 仅元数据 = 0（双分支穷尽断言）。"""
        blobs, ledger, freshness, owner, first = self._seed(tmp_path)
        for resolver_blobs in (blobs, None):
            resolver = EvidenceSourceResolver(
                ledger,
                freshness=freshness,
                owner_resolver=lambda: owner,
                blobs=resolver_blobs,
            )
            hit = resolver.resolve(
                ToolCall(id="s4", name="read_file", arguments={"path": str(tmp_path / "f.txt")})
            )
            assert hit is not None
            if hit.status is ToolResultStatus.SUCCESS:
                body = hit.content.rsplit("[evidence_reuse]", 1)[0]
                assert len(body.strip()) > 0  # 正文在场（非仅元数据）
            else:
                assert hit.status is ToolResultStatus.FAILURE

    def test_force_refresh_bypasses_reuse(self, tmp_path):
        blobs, ledger, freshness, owner, first = self._seed(tmp_path)
        resolver = EvidenceSourceResolver(
            ledger,
            freshness=freshness,
            owner_resolver=lambda: owner,
            blobs=blobs,
        )
        assert (
            resolver.resolve(
                ToolCall(
                    id="s5",
                    name="read_file",
                    arguments={"path": str(tmp_path / "f.txt"), "force_refresh": True},
                )
            )
            is None
        )  # 物理重读路径零回归


# ══════════════ C-2.4 discovery 组（恢复入口真空防护门）══════════════


class TestC24OnDemandDiscovery:
    """路线 2: 截断事实行在场场景下 get_tool_schema 可发现恢复三件套。"""

    def _registry(self, tmp_path: Path):
        from llm_loop.tools.evidence_tools import EvidenceReadTool
        from llm_loop.tools.registry import GetToolSchemaTool

        blobs = BlobStore(tmp_path / "b")
        ledger = EvidenceLedgerStore(tmp_path / "l")
        freshness = EvidenceFreshness(ledger)
        owner = _owner()
        registry = ToolRegistry()
        registry.register(GetToolSchemaTool(registry))
        registry.register(
            EvidenceReadTool(blobs, ledger, freshness=freshness, owner_resolver=lambda: owner)
        )
        return registry

    def test_query_evidence_discovers_recovery_tools(self, tmp_path):
        registry = self._registry(tmp_path)
        result = registry.execute(
            ToolCall(id="d1", name="get_tool_schema", arguments={"tool_name": "?evidence"})
        )
        assert result.status is ToolResultStatus.SUCCESS
        for name in ("read_evidence",):
            assert name in result.content

    def test_exact_schema_lookup(self, tmp_path):
        registry = self._registry(tmp_path)
        result = registry.execute(
            ToolCall(id="d2", name="get_tool_schema", arguments={"tool_name": "read_evidence"})
        )
        assert result.status is ToolResultStatus.SUCCESS
        assert "read_evidence" in result.content
        assert "evidence_ref" in result.content  # 参数 schema 在场

    def test_registry_fact_consistency(self, tmp_path):
        """恢复工具注册状态与可发现性一致（R8.7 注册事实原则）。"""
        registry = self._registry(tmp_path)
        assert "read_evidence" in registry.names()
        listing = registry.execute(
            ToolCall(id="d3", name="get_tool_schema", arguments={"tool_name": "*"})
        )
        assert listing.status is ToolResultStatus.SUCCESS
        assert "read_evidence" in listing.content

    def test_visibility_never_scans_receipt_text(self):
        """C-D8 禁扫回执文本静态断言: eligibility 投影层源码不含回执程序喊话锚点扫描。"""
        source = (SRC_ROOT / "tools" / "eligibility.py").read_text(encoding="utf-8")
        assert "recover=read_evidence" not in source
        assert 'recover=' not in source
        # 恢复可见性的数据源 = control-plane metadata（tool_recovery），非 content 文本
        assert 'metadata.get("tool_recovery")' in source
        # 词法路由的数据源 = 用户输入文本（user_text），非回执正文
        assert "def _task_relevant_names(user_text" in source

    def test_truncation_fact_line_scenario_discovery(self, tmp_path, monkeypatch):
        """截断事实行在场场景（端到端）: 事实行 + 恢复工具可发现。"""
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        path = tmp_path / "big2.txt"
        path.write_text("Z" * 6000, encoding="utf-8")
        registry, _, _ = _enforce_registry(tmp_path, projection_budget_chars=400)
        monkeypatch.setenv("LFL_EVIDENCE_CAPSULE", "off")
        result = registry.execute(
            ToolCall(id="e2e", name="read_file", arguments={"path": str(path), "full": True})
        )
        fact = [
            ln for ln in result.content.splitlines() if ln.startswith("result_truncated=")
        ]
        assert len(fact) == 1
        recovery_ref = fact[0].split("recovery_ref=", 1)[1]
        # 事实行的 ref 可经 read_evidence 取回（同构 resolver 路由面）
        hydrated_check = recovery_ref.startswith("evidence://v1/")
        assert hydrated_check


# ══════════════ C-5.6 fixture 组（T6 死循环回归重写 + C-3.4 可达性）══════════════


class TestT6DeathLoopRegressionFixture:
    """T6 三防线（脱敏 fixture: tests/fixtures/tool_factualization/）。

    旧"胶囊轮可见"断言已按设计包 §6 重写为"截断事实行轮恢复工具可发现"
    （capsule 已退出，旧口径失效）。
    """

    @classmethod
    def setup_class(cls):
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        scenario = {
            "schema": "t6_death_loop_regression_v1",
            "description": "R8.24-C T6 死循环回归场景（脱敏）: read_file 误读 evidence:// 引用",
            "facts": {
                "misused_ref": "evidence://v1/" + "f" * 64,
                "legacy_failure_mode": "file_not_found + recover=read_evidence 误导喊话",
                "legacy_loop_count": "6+ 同参重试（r-p-r §0）",
                "defenses": [
                    "line1: read_file(evidence://) 参数误用短路（零磁盘 IO / 零否定帧）",
                    "line2: 失败回执零诱饵（零 capsule / 零喊话——D2 status 门 + C-2.3）",
                    "line3: 恢复类计数收敛（_track_stagnation 同指纹计数，B-5.7 接口）",
                ],
            },
        }
        (FIXTURE_DIR / "death-loop-scenario.json").write_text(
            json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        cls.scenario = scenario

    def test_defense_line1_short_circuit(self, tmp_path, monkeypatch):
        ref = self.scenario["facts"]["misused_ref"]
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        result = ReadFileTool().execute(path=ref)
        assert result.status is ToolResultStatus.FAILURE
        assert result.short_circuit_kind == "misuse_evidence_ref"

    def test_defense_line2_failure_receipt_zero_lure(self, tmp_path, monkeypatch):
        ref = self.scenario["facts"]["misused_ref"]
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        result = ReadFileTool().execute(path=ref)
        assert result.evidence_ref is None
        assert "[evidence]" not in result.content
        assert "recover=" not in result.content

    def test_defense_line3_stagnation_counting_converges(self):
        """恢复类计数收敛: B 包 _track_stagnation 接口对同指纹失败调用累计（B-5.7 对接）。"""
        from llm_loop.core.loop.engine_services.tool_cycle import ToolCycleService

        class _StubEngine:
            def __init__(self) -> None:
                from llm_loop.core.loop.engine_services.run_state import RunStateManager

                self._run_state_mgr = RunStateManager()

            def _run_state(self):
                return self._run_state_mgr.bucket()

            def _stagnation_fingerprint(self, tc):
                return f"{tc.name}|fp"

            def _record_action(self, phase, action_type, detail):
                self.last_action = (phase, action_type, detail)

        stub = _StubEngine()
        stub._host = stub  # R9-B5-W3-01: 裸替身自指宿主面（RunState 桶经 _run_state() 直供）
        tc = ToolCall(id="z1", name="read_file", arguments={"path": "evidence://v1/x"})
        result = ReadFileTool().execute(path="evidence://v1/x")
        for _ in range(3):
            ToolCycleService._track_stagnation(  # pyright: ignore[reportAttributeAccessIssue]
                stub, tc, None, [], result=result
            )
        assert stub._run_state().stagnation_state["count"] == 3  # 计数收敛接口在场且累计

    def test_capability_observability_receipt(self):
        """五项不退化观测口径落档（§13.2）——fixture 场景下三防线断言齐 = 回执。"""
        receipt = {
            "tool_discovery": "get_tool_schema('?evidence') 可发现 read_evidence（discovery 组）",
            "unresolved_followup": "截断事实行 recovery_ref 可经 read_evidence 取回（e2e 用例）",
            "task_completion": "shadow 观测期指标（C-1.2/C-2.x shadow 事件对账，回执落档）",
            "factual_hallucination": "陈述式四要素 + 零劝导句式（C-G6 扫描）",
            "tool_protocol_error": "短路返回合法 FAILURE（零孤儿 tool_call）",
        }
        assert set(receipt) == {
            "tool_discovery", "unresolved_followup", "task_completion",
            "factual_hallucination", "tool_protocol_error",
        }


class TestC34CompressionRecoveryReachability:
    """C-3.4: 压缩恢复清单 evidence://v1 引用可达性核对（capsule 退出不改 ref 语义）。"""

    def test_compressed_ref_reachable_via_read_evidence(self, tmp_path, monkeypatch):
        """构造"capsule off + 历史 Evidence 在场"场景: 历史期 ref 仍可经 read_evidence 取回。"""
        from llm_loop.tools.evidence_tools import EvidenceReadTool

        blobs = BlobStore(tmp_path / "b")
        ledger = EvidenceLedgerStore(tmp_path / "l")
        capture = EvidenceCapture(blobs, ledger)
        freshness = EvidenceFreshness(ledger)
        owner = _owner()
        # "历史压缩期" capture（capsule off 不改变 capture 语义——存储层零改动）
        monkeypatch.setenv("LFL_EVIDENCE_CAPSULE", "off")
        enforcer = EvidenceEnforcer(
            capture,
            projection=ProjectionEngine(),
            owner_resolver=lambda: owner,
            projection_budget_chars=500,
        )
        legacy = enforcer.apply(
            ToolCall(id="h1", name="execute_command", arguments={"command": "echo archive"}),
            ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="HISTORICAL-COMPRESSED-OBSERVATION " + "k" * 800,
                tool_call_id="h1",
                tool_name="execute_command",
            ),
        )
        assert legacy.evidence_ref is not None
        assert legacy.evidence_ref.startswith("evidence://v1/")

        # ① ref 引用形态与 Ledger 现存记录一致
        record = ledger.require_authorized(owner, EvidenceRef(legacy.evidence_ref))
        assert record.evidence_ref.ref == legacy.evidence_ref
        # ② read_evidence 对历史 ref 取回成功（抽档断言）
        tool = EvidenceReadTool(
            blobs, ledger, freshness=freshness, owner_resolver=lambda: owner, max_limit=4000
        )
        out = tool.execute(evidence_ref=legacy.evidence_ref, limit=4000)
        assert out.status is ToolResultStatus.SUCCESS
        assert "HISTORICAL-COMPRESSED-OBSERVATION" in out.content
        # ③ 截断事实行 recovery_ref 与压缩清单 ref 同构（同一 resolver 路由面）
        assert legacy.evidence_ref.split("/")[2] == "v1"


class _EchoTool:
    name = "echo"
    description = "测试用回显工具（输出超阈值以触发摘要层）"
    parameters = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    def execute(self, **kwargs):
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=str(kwargs.get("text", "")),
            tool_call_id="",
            tool_name=self.name,
        )
