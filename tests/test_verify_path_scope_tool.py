"""verify_path_scope 只读观测工具回归（DESIGN-20261030 §5.3 C9 / FR-11 / T14）。

契约：纯只读地报告 (1) 当前生效 write scope（mode + pattern 集合，或全量）、
(2) 审计快照 written_paths、(3) violation_count + 逐条明细（path + reason）。
纪律：不写文件、不改状态、不回显文件内容；依赖未部署 → 确定性 FAILURE
（fail-closed，绝不把"看不见"伪报成"0 次越界"）。

并行交付边界：core/write_scope.py 与 run_context.current_write_scope 由并行
agent 交付（快照 API 已钉死）。未就绪时运行时用例 skip（如实说明），不伪造通过。
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from llm_loop.tools.builtin.verify_path_scope import VerifyPathScopeTool
from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS, ToolRegistry

# ---- 并行依赖就绪探测（C4/C9 契约：run_context.current_write_scope + core.write_scope）----
try:
    _RUN_CONTEXT = importlib.import_module("llm_loop.core.run_context")
except ImportError:  # pragma: no cover - run_context 是既有模块
    _RUN_CONTEXT = None
_SCOPE_VAR = getattr(_RUN_CONTEXT, "current_write_scope", None) if _RUN_CONTEXT else None

try:
    _WRITE_SCOPE = importlib.import_module("llm_loop.core.write_scope")
except ImportError:
    _WRITE_SCOPE = None

_RUNTIME_READY = _SCOPE_VAR is not None and _WRITE_SCOPE is not None
_REASON = (
    "并行依赖未就绪：core/write_scope.py / run_context.current_write_scope "
    "尚未交付（C4/C9 契约）"
)

requires_runtime = pytest.mark.skipif(not _RUNTIME_READY, reason=_REASON)
requires_missing_runtime = pytest.mark.skipif(
    _RUNTIME_READY, reason="依赖已就绪，未就绪分支不适用"
)


def _run_tool() -> object:
    return VerifyPathScopeTool().execute()


# ---------- 元数据 / 注册（不依赖并行交付，始终运行） ----------


def test_tool_metadata_and_compact_description() -> None:
    tool = VerifyPathScopeTool()
    assert tool.name == "verify_path_scope"
    assert "何时用" in tool.description
    assert "何时不用" in tool.description
    assert tool.parameters == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    compact = _COMPACT_TOOL_DESCRIPTIONS.get("verify_path_scope")
    assert isinstance(compact, str) and compact
    assert "只读" in compact
    assert "越界" in compact


def test_registry_lookup_name_and_description() -> None:
    reg = ToolRegistry()
    reg.register(VerifyPathScopeTool())
    assert "verify_path_scope" in reg.names()
    full = {d["name"]: d for d in reg.schemas(lazy=False)}
    assert full["verify_path_scope"]["description"] == VerifyPathScopeTool.description
    assert full["verify_path_scope"]["parameters"] == VerifyPathScopeTool.parameters


def test_factory_registers_tool_with_compact_description(tmp_path, monkeypatch) -> None:
    """真实 build_engine 装配后，verify_path_scope 在工具面且 lazy 描述取自 curated 条目。"""
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EXTRACT_ENABLED", "0")
    monkeypatch.setenv("SUMMARY_MODE", "off")
    from llm_loop.config import load_settings
    from llm_loop.factory import build_engine

    engine = build_engine(load_settings())
    lazy = {d["name"]: d for d in engine.registry.schemas(lazy=True)}
    assert "verify_path_scope" in lazy
    assert (
        lazy["verify_path_scope"]["description"]
        == _COMPACT_TOOL_DESCRIPTIONS["verify_path_scope"]
    )


# ---------- 依赖未就绪：fail-closed（仅缺失时运行） ----------


@requires_missing_runtime
def test_missing_runtime_dependency_fails_closed() -> None:
    result = _run_tool()
    assert result.status == "failure"
    assert "未部署" in result.content or "未就绪" in result.content


# ---------- 运行时行为（依赖就绪后运行） ----------


@requires_runtime
def test_scope_none_reports_full_access() -> None:
    token = _SCOPE_VAR.set(None)
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "全量" in result.content
    assert "current_write_scope=None" in result.content


@requires_runtime
def test_scope_reports_mode_and_patterns() -> None:
    scope = SimpleNamespace(mode="allow", allow=["src/**", "docs/*.md"], deny=[])
    token = _SCOPE_VAR.set(scope)
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "受限" in result.content
    assert "allow" in result.content
    assert "src/**" in result.content
    assert "docs/*.md" in result.content


@requires_runtime
def test_scope_pattern_truncation_notes_total() -> None:
    patterns = [f"dir{i}/**" for i in range(25)]
    scope = SimpleNamespace(mode="allow", allow=patterns, deny=[])
    token = _SCOPE_VAR.set(scope)
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "总数 25 条" in result.content
    assert "dir24/**" not in result.content  # 超出前 20 条的 pattern 不回显
    assert "dir19/**" in result.content


@requires_runtime
def test_scope_unknown_shape_degrades_honestly() -> None:
    token = _SCOPE_VAR.set(SimpleNamespace())
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "未识别" in result.content


@requires_runtime
def test_audit_snapshot_reflected_faithfully(monkeypatch) -> None:
    snapshot = {
        "written_paths": ["/w/src/a.py", "/w/docs/b.md"],
        "violations": [
            {"path": "/etc/hosts", "reason": "outside_scope"},
            {"path": "../secrets.env", "reason": "not_in_allow_list"},
        ],
        "violation_count": 2,
    }
    monkeypatch.setattr(_WRITE_SCOPE, "write_scope_audit_snapshot", lambda: dict(snapshot))
    token = _SCOPE_VAR.set(None)
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "/w/src/a.py" in result.content
    assert "/w/docs/b.md" in result.content
    assert "越界写入尝试: 2 次" in result.content
    assert "/etc/hosts — outside_scope" in result.content
    assert "../secrets.env — not_in_allow_list" in result.content


@requires_runtime
def test_written_paths_and_violation_details_truncated(monkeypatch) -> None:
    snapshot = {
        "written_paths": [f"/w/f{i}.py" for i in range(60)],
        "violations": [
            {"path": f"/bad/{i}.txt", "reason": "outside_scope"} for i in range(25)
        ],
        "violation_count": 25,
    }
    monkeypatch.setattr(_WRITE_SCOPE, "write_scope_audit_snapshot", lambda: dict(snapshot))
    token = _SCOPE_VAR.set(None)
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "共 60 条，仅显示前 50 条" in result.content
    assert "/w/f59.py" not in result.content
    assert "/w/f49.py" in result.content
    assert "明细共 25 条，仅显示前 20 条" in result.content
    assert "/bad/24.txt" not in result.content
    assert "/bad/19.txt" in result.content


@requires_runtime
def test_violation_count_authoritative_over_detail_length(monkeypatch) -> None:
    """快照计数与明细长度不一致时，以快照计数为准并明示。"""
    snapshot = {
        "written_paths": [],
        "violations": [{"path": "/bad/one", "reason": "outside_scope"}],
        "violation_count": 7,
    }
    monkeypatch.setattr(_WRITE_SCOPE, "write_scope_audit_snapshot", lambda: dict(snapshot))
    token = _SCOPE_VAR.set(None)
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "越界写入尝试: 7 次" in result.content
    assert "不一致" in result.content


@requires_runtime
def test_tool_is_readonly_snapshot_and_tree_unchanged(tmp_path, monkeypatch) -> None:
    """只读性：调用前后审计快照钉死字段不变、目录清单不变、目标文件字节不变。"""
    marker = "SECRET_MARKER_CONTENT_9f3a"
    canary = tmp_path / "canary.txt"
    canary.write_text(marker + "\n", encoding="utf-8")
    before_bytes = canary.read_bytes()
    before_listing = sorted(p.name for p in tmp_path.iterdir())

    real_snapshot = _WRITE_SCOPE.write_scope_audit_snapshot
    before_pinned = {
        k: real_snapshot().get(k) for k in ("written_paths", "violations", "violation_count")
    }
    # 诱因：审计与 scope 都指向 canary，工具若读内容即泄漏 marker
    monkeypatch.setattr(
        _WRITE_SCOPE,
        "write_scope_audit_snapshot",
        lambda: {"written_paths": [str(canary)], "violations": [], "violation_count": 0},
    )
    token = _SCOPE_VAR.set(SimpleNamespace(mode="allow", allow=[str(canary)], deny=[]))
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
        monkeypatch.undo()

    assert result.status == "success", result.content
    # 输出只含路径与计数，绝不含文件内容
    assert str(canary) in result.content
    assert marker not in result.content
    # 无写副作用：字节、清单、审计钉死字段前后一致
    assert canary.read_bytes() == before_bytes
    assert sorted(p.name for p in tmp_path.iterdir()) == before_listing
    after_pinned = {
        k: real_snapshot().get(k) for k in ("written_paths", "violations", "violation_count")
    }
    assert after_pinned == before_pinned


# ---------- 与并行交付的真实实现集成 ----------


@requires_runtime
def test_real_write_scope_object_reported() -> None:
    """真实 WriteScope（交付类）：mode/paths/deny_paths 如实呈现。"""
    scope = _WRITE_SCOPE.WriteScope(
        paths=("src/**", "docs/*.md"), mode="allow", deny_paths=("secrets/**",)
    )
    token = _SCOPE_VAR.set(scope)
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "受限" in result.content
    assert "allow" in result.content
    assert "src/**" in result.content
    assert "docs/*.md" in result.content
    assert "secrets/**" in result.content  # deny_paths 必须可见


@requires_runtime
def test_real_write_scope_undeclared_normalized_to_full() -> None:
    """declared=False 按交付语义归一为"未声明=继承"（等价全量），观测面同口径。"""
    scope = _WRITE_SCOPE.WriteScope(paths=(), declared=False)
    token = _SCOPE_VAR.set(scope)
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "全量" in result.content
    assert "declared=False" in result.content


@requires_runtime
def test_real_audit_reflection_with_state_restore() -> None:
    """经真实记录 API 写入审计 → 工具如实反映 → 恢复原审计状态。"""
    saved = _WRITE_SCOPE.write_scope_audit_snapshot()
    try:
        _WRITE_SCOPE.write_scope_audit_reset()
        _WRITE_SCOPE.write_scope_audit_record_write("/real/w/a.py")
        _WRITE_SCOPE.write_scope_audit_record_violation("/real/bad", "outside_scope")
        token = _SCOPE_VAR.set(None)
        try:
            result = _run_tool()
        finally:
            _SCOPE_VAR.reset(token)
        assert result.status == "success", result.content
        assert "/real/w/a.py" in result.content
        assert "越界写入尝试: 1 次" in result.content
        assert "/real/bad — outside_scope" in result.content
    finally:
        _WRITE_SCOPE.write_scope_audit_reset()
        for path in saved.get("written_paths", []) or []:
            _WRITE_SCOPE.write_scope_audit_record_write(str(path))
        for item in saved.get("violations", []) or []:
            if isinstance(item, dict):
                _WRITE_SCOPE.write_scope_audit_record_violation(
                    str(item.get("path", "")), str(item.get("reason", ""))
                )


# ---------- 返修 B：按 mode 区分允许集/排除集语义标注 ----------
#
# 修前问题：工具按属性名裸列 pattern（``- paths (1 条): secrets/**``），
# 同一属性名在 allow/deny 两种 mode 下语义相反——deny 模式的排除集会被
# 误读成允许集。修后按 mode 标注：allow → 「允许写入路径（未命中即拒绝写）」，
# deny → 「排除路径（命中即拒；排除集之外均允许写）」；deny_paths（父链
# 叠加 deny 集）单独标注为「继承/叠加的排除路径」。纯只读性由既有
# test_tool_is_readonly_snapshot_and_tree_unchanged 覆盖，不重复。


@requires_runtime
def test_deny_mode_paths_labeled_as_exclusion_semantics() -> None:
    """返修 B：mode=deny 时 paths 标注为排除语义，不得出现 allow 语义标签."""
    scope = _WRITE_SCOPE.WriteScope(paths=("secrets/**", "tmp/*"), mode="deny")
    token = _SCOPE_VAR.set(scope)
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "模式(mode): deny" in result.content
    assert "排除路径" in result.content  # paths 被标注为排除集
    assert "命中即拒" in result.content
    assert "排除集之外均允许" in result.content  # 说明排除集之外均允许
    assert "secrets/**" in result.content
    assert "tmp/*" in result.content
    # deny 模式下不得出现把 paths 标成允许集的措辞
    assert "允许写入路径" not in result.content


@requires_runtime
def test_allow_mode_paths_labeled_as_allow_semantics() -> None:
    """返修 B：mode=allow 时 paths 标注为「允许写入路径（未命中即拒绝写）」."""
    scope = _WRITE_SCOPE.WriteScope(paths=("src/**", "docs/*.md"), mode="allow")
    token = _SCOPE_VAR.set(scope)
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "模式(mode): allow" in result.content
    assert "允许写入路径" in result.content
    assert "未命中即拒绝写" in result.content
    assert "src/**" in result.content
    # 无 deny 成分时不出现排除语义标签
    assert "排除路径" not in result.content


@requires_runtime
def test_deny_paths_labeled_as_inherited_exclusion() -> None:
    """返修 B：deny_paths（父链叠加 deny 集）单独标注「继承/叠加的排除路径」."""
    scope = _WRITE_SCOPE.WriteScope(
        paths=("src/**",), mode="allow", deny_paths=("secret/**",)
    )
    token = _SCOPE_VAR.set(scope)
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "继承/叠加的排除路径" in result.content
    assert "优先于允许集" in result.content
    assert "secret/**" in result.content
    # allow 集与叠加排除集两组同时呈现、各自语义明确
    assert "允许写入路径" in result.content
    assert "src/**" in result.content


@requires_runtime
def test_allow_mode_empty_paths_noted_as_readonly() -> None:
    """返修 B：allow 模式空 paths 观测面注明=只读（拒绝一切写），不误读为无约束."""
    scope = _WRITE_SCOPE.WriteScope(paths=(), mode="allow", declared=True)
    token = _SCOPE_VAR.set(scope)
    try:
        result = _run_tool()
    finally:
        _SCOPE_VAR.reset(token)
    assert result.status == "success", result.content
    assert "受限" in result.content
    assert "只读" in result.content
    assert "拒绝一切写" in result.content


@requires_runtime
def test_audit_dropped_count_surfaced() -> None:
    """第三轮审查 P2-2：审计条目超上限被丢弃时，观测面必须显性报出丢弃数。

    丢弃发生时明细不完整——不报出来，读者会把「少了几条」误读成「没有那么多」。
    """
    saved = _WRITE_SCOPE.write_scope_audit_snapshot()
    try:
        _WRITE_SCOPE.write_scope_audit_reset()
        overflow = 3
        for index in range(_WRITE_SCOPE._AUDIT_MAX_ENTRIES + overflow):
            _WRITE_SCOPE.write_scope_audit_record_unverified(
                f"/unverified/{index}", "scope_unverified"
            )
        token = _SCOPE_VAR.set(None)
        try:
            result = _run_tool()
        finally:
            _SCOPE_VAR.reset(token)
        assert result.status == "success", result.content
        assert "丢弃" in result.content, result.content
        assert str(overflow) in result.content, result.content
    finally:
        _WRITE_SCOPE.write_scope_audit_reset()
        for path in saved.get("written_paths", []) or []:
            _WRITE_SCOPE.write_scope_audit_record_write(str(path))
        for item in saved.get("violations", []) or []:
            if isinstance(item, dict):
                _WRITE_SCOPE.write_scope_audit_record_violation(
                    str(item.get("path", "")), str(item.get("reason", ""))
                )
