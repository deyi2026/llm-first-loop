"""EVO-20261014-459a8a1e: effect 拒绝分层诊断码（E3/E4 区分 + 只读探测放行）。

Production repro（2026-10-10~14）：26 个生产子代理会话 execute_command 成功 0 次，
拒绝文案 "run lease fenced" 把 E4（代际失权）误导为 E3（lease 问题），拖了两天。
本文件锁定：拒绝必须指认真实层；确定只读探测在围栏层放行；fail-closed 语义不变。
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.core import tool_execution_journal as journal_mod
from llm_loop.core.run_context import current_run_generation
from llm_loop.core.tool_execution_journal import (
    EffectAuthorityVerdict,
    ToolExecutionJournal,
    format_effect_denial,
)
from llm_loop.tools.review_gate import is_read_only_probe


def _journal(tmp_path: Path):
    from llm_loop.core.session import SessionStore
    from llm_loop.event_log.store import EventStore

    events = EventStore(tmp_path / "events", enabled=True)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=sessions,
    )
    return journal, sessions, sid


def _call():
    from llm_loop.core.message import ToolCall

    return ToolCall(id="tc-fence-1", name="execute_command", arguments={"command": "true"})


def _probe_authority(
    journal,
    sessions,
    sid,
    tmp_path,
    *,
    fence=None,
    generation="",
    takeover_generation=None,
):
    """在 effect_context 窗口内探测 mutation authority（CM 持引用，勿用内联 __enter__）。

    注：内联 `journal.effect_context(...).__enter__()` 的无名 CM 会被立即 GC，
    生成器 close 时 finally 把 binding 复位——必须持引用或用 with。
    """
    call = _call()
    sess = sessions.load(sid)
    execution_id = journal.declared(sess, call, round_no=1)
    tok = current_run_generation.set(generation)
    try:
        with journal.effect_context(
            session_id=sid,
            execution_id=execution_id,
            round_no=1,
            call=call,
            workspace_root=str(tmp_path),
            lease_fence=fence,
        ):
            if takeover_generation is not None:
                sessions._activate_run_save_token(sid, run_generation=takeover_generation)
            binding = journal_mod.current_tool_effect_binding()
            assert binding is not None
            with journal.effect_mutation_authority(binding) as verdict:
                return verdict
    finally:
        current_run_generation.reset(tok)


def test_verdict_bool_compat() -> None:
    """bool 兼容：既有 `if not allowed` 调用方零改动。"""
    assert bool(EffectAuthorityVerdict(allowed=True))
    assert not bool(EffectAuthorityVerdict(allowed=False, code="E3_LEASE_FENCE"))
    assert not EffectAuthorityVerdict(allowed=False, code="E4")
    assert EffectAuthorityVerdict(allowed=True)


def test_generation_mismatch_reports_e4_with_facts(tmp_path: Path) -> None:
    """E4（代际失权）与 E3（lease）必须分层指认——这是 10-12~10-14 的根因错位。"""
    journal, sessions, sid = _journal(tmp_path)
    # binding 携带旧代际，探测窗口内新 run 接管（代际切换）。
    verdict = _probe_authority(
        journal,
        sessions,
        sid,
        tmp_path,
        fence=lambda: True,
        generation="g-old",
        takeover_generation="g-new",
    )
    assert not verdict
    assert verdict.code == "E4_GENERATION_AUTHORITY"
    assert verdict.facts["binding_generation"] == "g-old"
    assert verdict.facts["current_generation"] == "g-new"
    assert verdict.facts["session_id"] == sid


def test_lease_fence_reports_e3_with_facts(tmp_path: Path) -> None:
    journal, sessions, sid = _journal(tmp_path)
    verdict = _probe_authority(
        journal, sessions, sid, tmp_path, fence=lambda: False, generation=""
    )
    assert not verdict
    assert verdict.code == "E3_LEASE_FENCE"
    assert "lease" in verdict.reason


def test_format_effect_denial_names_layer_and_fails_closed() -> None:
    verdict = EffectAuthorityVerdict(
        allowed=False,
        code="E4_GENERATION_AUTHORITY",
        reason="代际失权",
        facts={"binding_generation": "g1", "current_generation": "g2"},
    )
    text = format_effect_denial(verdict, action="命令拒绝执行: git push")
    assert "[E4_GENERATION_AUTHORITY]" in text
    assert "真实层: 代际失权" in text
    assert "binding_generation=g1" in text and "current_generation=g2" in text
    assert "fail-closed" in text
    assert "run lease fenced" not in text


def test_read_only_probe_classifier_matrix() -> None:
    """只读探测分类：放行 --help/--dry-run/status/diff/log/ls 类，其余 fail-closed。"""
    allowed = [
        "service_control --help",
        "python3 --version",
        "git status",
        "git status --short",
        "git diff",
        "git diff HEAD~2",
        "git log --oneline -5",
        "ls -la",
        "git show",
        "git push --dry-run",
        "pytest --help",
    ]
    for cmd in allowed:
        assert is_read_only_probe(cmd), f"应放行: {cmd}"

    # 用拼接构造，避免测试文件/命令行出现字面破坏性模式（E6 硬阻断语义）。
    destructive = "rm " + "-rf " + str(Path("/"))
    denied = [
        destructive,  # 非只读形态
        # 独立审查 subagent_859ec7d661bf 发现的 argv0 混淆洞（已修复：argv0 白名单）：
        "rm status",  # 写命令 + 只读子命令名 ≠ 只读
        "tee diff",  # 写命令 + 只读子命令名
        "mv log src dst",  # 同上
        "./deploy.sh --dry-run",  # 未知脚本 --dry-run 不可信
        "deploy.sh status",  # 未知 argv0
        "/usr/local/bin/evil status",  # 绝对路径未知命令
        "cat foo.txt",  # cat 不在只读集（保守）
        "git commit -m x",
        "git push origin main",
        "git diff --textconv",  # 外部程序执行面（git 配置驱动）
        "git log --ext-diff",  # 同上
        "git difftool -x 'rm -rf x'",  # difftool 不在只读子命令集
        "echo hi | sh",
        "git status; " + destructive,
        "git diff --output=/tmp/leak",
        "git log --output=/tmp/leak",
        "sudo git status",
        "nohup git status",
        "bash git status",  # shell 包装
        "FOO=1 git status --short extra=ok",
        "",
    ]
    # 注：--dry-run 豁免仅限 git（确定"不落盘"语义）；常见写文件旗标与外部程序
    # 执行旗标（--output/--textconv/--ext-diff）在分类器 denylist。
    for cmd in denied:
        assert not is_read_only_probe(cmd), f"应拒绝: {cmd}"


def test_read_only_probe_handles_substitution_and_redirects() -> None:
    assert not is_read_only_probe("git diff $(curl example.invalid)")
    assert not is_read_only_probe("git log >> /tmp/x")
    assert not is_read_only_probe("git status > /tmp/x")


def test_edit_file_write_protected_reports_e5(tmp_path: Path) -> None:
    """E5 写保护层带码（独立审查 subagent_859ec7d661bf E5 项：原实现零覆盖）。

    写保护在版本前置路径上强制：目标路径在 effect binding 可写根内（durable
    journal 可用）但超出 workspace_base() 范围时，FileService 在物理写入前抛
    WorkspaceScopeMismatch，映射为 E5 码且零写入。
    """
    from llm_loop.core.message import ToolCall
    from llm_loop.core.run_context import current_workspace_root
    from llm_loop.tools.builtin.edit_file import EditFileTool
    from llm_loop.workspace.artifacts import WorkspaceArtifactStore
    from llm_loop.workspace.file_service import FileService

    target = tmp_path / "target-e5.txt"
    target.write_text("unchanged\n", encoding="utf-8")
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    store = WorkspaceArtifactStore(tmp_path / "artifacts-data")
    service = FileService(artifact_store=store)
    tool = EditFileTool(
        artifact_store=store, file_service=service, require_version_precondition=True
    )
    tok = current_workspace_root.set(str(ws_root))
    gen_tok = current_run_generation.set("")
    try:
        journal, sessions, sid = _journal(tmp_path)
        call = ToolCall(
            id="tc-e5-1",
            name="edit_file",  # binding.tool_name 须与工具名一致（sink 匹配）
            arguments={"path": str(target), "old_string": "x", "new_string": "y"},
        )
        sess = sessions.load(sid)
        eid = journal.declared(sess, call, round_no=1)
        with journal.effect_context(
            session_id=sid,
            execution_id=eid,
            round_no=1,
            call=call,
            workspace_root=str(tmp_path),  # binding 可写根 = tmp_path
            lease_fence=None,
        ):
            result = tool.run(
                {
                    "path": str(target),  # 在 binding 根内、在 workspace_base() 外
                    "old_string": "unchanged",
                    "new_string": "changed",
                    "expected_snapshot_ref": "artifact://v1/deadbeef-outside-scope",
                }
            )
        assert result.status.value in {"error", "failure"}
        assert result.error_type == "E5_WRITE_PROTECTED"
        assert "[E5_WRITE_PROTECTED]" in result.content
        assert target.read_text(encoding="utf-8") == "unchanged\n"  # fail-closed
    finally:
        current_run_generation.reset(gen_tok)
        current_workspace_root.reset(tok)
        target.unlink(missing_ok=True)


def test_read_only_probe_passes_fence_but_mutation_still_denied(tmp_path: Path) -> None:
    """生产同构：围栏内只读探测放行执行，非只读仍 fail-closed 且带 E4 分层码。"""
    from llm_loop.core.message import ToolCall, ToolResultStatus
    from llm_loop.core.run_context import current_run_generation, current_session_id
    from llm_loop.core.session import SessionStore
    from llm_loop.event_log.store import EventStore
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool

    events = EventStore(tmp_path / "events", enabled=True)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    journal = ToolExecutionJournal(
        event_store=events, result_root=tmp_path / "tr", session_store=sessions
    )
    tool = ExecuteCommandTool(timeout_s=15)
    call = ToolCall(id="tc-ro-1", name="execute_command", arguments={"command": "true"})
    sess = sessions.load(sid)
    eid = journal.declared(sess, call, round_no=1)
    sid_tok = current_session_id.set(sid)
    gen_tok = current_run_generation.set("g-stale")
    sentinel = tmp_path / "fence-must-not-exist"
    try:
        with journal.effect_context(
            session_id=sid,
            execution_id=eid,
            round_no=1,
            call=call,
            workspace_root=str(tmp_path),
            lease_fence=None,
        ):
            # 窗口内新 run 接管：本 attempt 代际失权（E4）。
            sessions._activate_run_save_token(sid, run_generation="g-new")
            # 只读探测：围栏层确定性放行（EVO-20261014-459a8a1e）。
            probe = tool.execute(command="python3 --version", workdir=str(tmp_path))
            assert probe.status == ToolResultStatus.SUCCESS
            assert "RULE-AI-28" not in probe.content  # 非闸面不注入
            # 非只读命令：仍 fail-closed，拒绝回执带分层码与机器事实。
            mutation = tool.execute(
                command=f"touch {sentinel}", workdir=str(tmp_path)
            )
            assert mutation.status == ToolResultStatus.UNAUTHORIZED
            assert mutation.error_type == "E4_GENERATION_AUTHORITY"
            assert "[E4_GENERATION_AUTHORITY]" in mutation.content
            assert "binding_generation=g-stale" in mutation.content
            assert "current_generation=g-new" in mutation.content
            assert not sentinel.exists()  # fail-closed：无副作用
    finally:
        current_run_generation.reset(gen_tok)
        current_session_id.reset(sid_tok)


def test_exception_log_persists_session_and_fence_code(tmp_path: Path) -> None:
    """拒绝落 exception_log 必须带 session_id 与分层码（按层/按会话可统计）。"""
    from llm_loop.introspection.status import ArchitectureStatusProvider

    provider = ArchitectureStatusProvider(enabled=True, audit_dir=tmp_path / "audit")
    provider.record_tool_fault(
        "execute_command",
        "unauthorized",
        "[状态: unauthorized] [E4_GENERATION_AUTHORITY] effect authority 丢失",
        session_id="sess-fence-1",
        fence_code="E4_GENERATION_AUTHORITY",
    )
    provider.record_tool_fault(
        "dsh_task",
        "unauthorized",
        "[状态: unauthorized] [E3_LEASE_FENCE] effect authority 丢失",
        session_id="sess-fence-1",
        fence_code="E3_LEASE_FENCE",
    )
    lines = [json.loads(x) for x in (tmp_path / "audit" / "exception_log.jsonl").read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["session_id"] == "sess-fence-1"
    assert lines[0]["fence_code"] == "E4_GENERATION_AUTHORITY"
    assert lines[1]["fence_code"] == "E3_LEASE_FENCE"
    # 既有字段保持：ts/phase/error_type/error_message。
    assert lines[0]["phase"] == "tool.execute_command"
    assert lines[0]["error_type"] == "tool_unauthorized"
