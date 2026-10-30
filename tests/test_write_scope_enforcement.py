"""写侧强制点验收（DESIGN-20261030 §5.3 C6/C7、§5.4、§5.5）.

覆盖 FileService.edit/observe 的 write_scope 判定门与 edit_file 工具的
确定性拒绝回执。判定算法本体（scope_allows）由 core/write_scope.py 交付并
另行测试；本文件只钉强制点行为：

- scope=None（默认）时 edit/observe 行为与现状逐字节一致（FR-3 回归）；
- allow pattern 内写入成功并记录审计 written_paths；
- 越界（pattern 外 / paths=[] / deny 优先 / glob 边界 / symlink 逃逸 /
  ``..`` 穿越与绝对路径越界）→ FileServiceError(error_type=
  "write_scope_violation")，且目标文件字节完全不变、无半成品（FR-5）；
- 拒绝回执不含文件内容（NFR-3），pattern 列表截断至 10 条并注明总数；
- 拒绝/成功分别落 violation / written 审计（write_scope_audit_snapshot）。

取舍已被测试钉死：scope 同时约束读与写（observe 同一 error_type，fail-closed，
理由见 file_service 模块 docstring）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from llm_loop.core.run_context import current_workspace_root, current_write_scope
from llm_loop.core.write_scope import (
    intersect_write_scope,
    parse_write_scope,
    write_scope_audit_reset,
    write_scope_audit_snapshot,
)
from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.workspace.artifacts import WorkspaceArtifactStore
from llm_loop.workspace.file_effects import FileArtifactProvenance
from llm_loop.workspace.file_service import FileService, FileServiceError

SECRET = "CONFIDENTIAL-7c1f-marker"  # must never appear in any rejection receipt


@pytest.fixture(autouse=True)
def _isolate_process_audit():
    """write_scope 审计是进程级全局（P0 已知边界），逐测试重置保证计数确定."""
    write_scope_audit_reset()
    yield
    write_scope_audit_reset()


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "src" / "a").mkdir(parents=True)
    (ws / "other").mkdir()
    return ws


def _service(tmp_path: Path, *, with_store: bool = False) -> FileService:
    store = WorkspaceArtifactStore(tmp_path / "artifacts") if with_store else None
    return FileService(artifact_store=store, lock_root=tmp_path / "locks")


def _seed(path: Path, text: str = "line one\nline two\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ── FR-3 / §5.10: scope=None = 全量 = 现状零行为变化 ──


def test_none_scope_edit_matches_legacy_behavior_exactly(tmp_path: Path) -> None:
    path = _seed(_workspace(tmp_path) / "src" / "a" / "legacy.txt")
    before = path.read_bytes()

    explicit_none = FileService().edit(
        path=path,
        old_string="line two",
        new_string="LINE TWO",
        write_scope=None,
    )
    assert explicit_none.applied is True
    assert explicit_none.actual_after_bytes == b"line one\nLINE TWO\n"

    omitted = FileService().edit(
        path=path, old_string="LINE TWO", new_string="line two"
    )  # 完全不传新参数 = 老调用形态
    assert omitted.applied is True
    assert path.read_bytes() == before


def test_none_scope_observe_matches_legacy_behavior(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    target = _seed(ws / "src" / "a" / "note.txt", "alpha\nbeta\n")
    service = _service(tmp_path, with_store=True)
    prov = FileArtifactProvenance(workspace_scope=str(ws), owner_session_id="t", operation_id="")

    observed = service.observe(
        path=target, workspace_scope=str(ws), provenance=prov, write_scope=None
    )
    assert observed.content == "alpha\nbeta\n"
    assert observed.path == "src/a/note.txt"
    legacy = service.observe(path=target, workspace_scope=str(ws), provenance=prov)
    assert legacy.content == observed.content
    assert legacy.sha256 == observed.sha256


# ── allow pattern 内：写入成功 + 审计 written_paths ──


def test_edit_within_allow_pattern_succeeds_and_records_written_path(
    tmp_path: Path,
) -> None:
    ws = _workspace(tmp_path)
    target = _seed(ws / "src" / "a" / "b.py", "x = 1\n")
    scope = parse_write_scope({"paths": ["src/**"], "mode": "allow"})

    result = FileService().edit(
        path=target,
        old_string="x = 1",
        new_string="x = 2",
        workspace_scope=str(ws),
        write_scope=scope,
    )

    assert result.applied is True
    assert target.read_bytes() == b"x = 2\n"
    snapshot = write_scope_audit_snapshot()
    assert str(target) in snapshot["written_paths"]
    assert snapshot["violation_count"] == 0


def test_dry_run_within_scope_does_not_record_written_path(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    target = _seed(ws / "src" / "d.py", "keep\n")
    scope = parse_write_scope({"paths": ["src/**"], "mode": "allow"})

    result = FileService().edit(
        path=target,
        old_string="keep",
        new_string="changed",
        dry_run=True,
        workspace_scope=str(ws),
        write_scope=scope,
    )

    assert result.applied is False
    assert target.read_bytes() == b"keep\n"
    assert write_scope_audit_snapshot()["written_paths"] == []


# ── 越界拒绝：字节不变、无半成品、审计 violation ──


def test_edit_outside_allow_rejected_bytes_unchanged_and_audited(
    tmp_path: Path,
) -> None:
    ws = _workspace(tmp_path)
    target = _seed(ws / "other" / "x.py", f"{SECRET}\n")
    before = target.read_bytes()
    scope = parse_write_scope({"paths": ["src/**"], "mode": "allow"})

    with pytest.raises(FileServiceError) as excinfo:
        FileService().edit(
            path=target,
            old_string=SECRET,
            new_string="replaced",
            workspace_scope=str(ws),
            write_scope=scope,
        )

    assert excinfo.value.error_type == "write_scope_violation"
    detail = excinfo.value.detail
    assert str(target) in detail
    assert "not_in_allow_list" in detail
    assert "src/**" in detail  # 允许 pattern 集合出现在回执
    assert "修正建议" in detail
    assert SECRET not in detail  # NFR-3: 不回显文件内容

    assert target.read_bytes() == before  # FR-5: 字节完全不变
    assert list((ws / "other").glob("*.tmp")) == []  # 无半成品/临时文件

    snapshot = write_scope_audit_snapshot()
    assert snapshot["violation_count"] == 1
    assert snapshot["violations"] == [
        {"path": str(target), "reason": "not_in_allow_list"}
    ]
    assert snapshot["written_paths"] == []


def test_empty_paths_rejects_write(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    target = _seed(ws / "src" / "ro.py", "immutable\n")
    before = target.read_bytes()
    readonly_scope = parse_write_scope({"paths": [], "mode": "allow"})  # FR-4

    assert readonly_scope is not None and readonly_scope.declared is True
    with pytest.raises(FileServiceError) as excinfo:
        FileService().edit(
            path=target,
            old_string="immutable",
            new_string="mutated",
            workspace_scope=str(ws),
            write_scope=readonly_scope,
        )

    assert excinfo.value.error_type == "write_scope_violation"
    assert "只读" in excinfo.value.detail  # 空 allow 集合的显式说明
    assert target.read_bytes() == before
    assert write_scope_audit_snapshot()["violation_count"] == 1


def test_deny_takes_precedence_over_allow(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    secret = _seed(ws / "secret" / "k.txt", "classified\n")
    normal = _seed(ws / "normal.txt", "fine\n")
    parent = parse_write_scope({"paths": ["**"], "mode": "allow"})
    child_deny = parse_write_scope({"paths": ["secret/**"], "mode": "deny"})
    effective, refusal = intersect_write_scope(parent, child_deny)
    assert refusal == "" and effective is not None

    with pytest.raises(FileServiceError) as excinfo:
        FileService().edit(
            path=secret,
            old_string="classified",
            new_string="leaked",
            workspace_scope=str(ws),
            write_scope=effective,
        )
    assert excinfo.value.error_type == "write_scope_violation"
    assert "denied_by_deny_list" in excinfo.value.detail
    assert secret.read_bytes() == b"classified\n"

    result = FileService().edit(
        path=normal,
        old_string="fine",
        new_string="edited",
        workspace_scope=str(ws),
        write_scope=effective,
    )
    assert result.applied is True  # deny 只排除清单内路径


def test_glob_boundary_src_globstar_hits_nested_and_src_star_misses_srcevil(
    tmp_path: Path,
) -> None:
    ws = _workspace(tmp_path)

    globstar = parse_write_scope({"paths": ["src/**"], "mode": "allow"})
    nested = _seed(ws / "src" / "a" / "b.py", "n = 1\n")
    ok = FileService().edit(
        path=nested,
        old_string="n = 1",
        new_string="n = 2",
        workspace_scope=str(ws),
        write_scope=globstar,
    )
    assert ok.applied is True  # src/** 命中 src/a/b.py（FR-6）

    star = parse_write_scope({"paths": ["src*"], "mode": "allow"})
    evil = _seed(ws / "srcevil" / "x.py", "evil = True\n")
    before = evil.read_bytes()
    with pytest.raises(FileServiceError) as excinfo:
        FileService().edit(
            path=evil,
            old_string="evil",
            new_string="evil2",
            workspace_scope=str(ws),
            write_scope=star,
        )
    assert excinfo.value.error_type == "write_scope_violation"
    assert evil.read_bytes() == before  # src* 不命中 srcevil/x.py（分隔符边界）


def test_symlink_inside_scope_pointing_outside_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    outside = _seed(tmp_path / "outside" / "real.py", "outside bytes\n")
    link_dir = ws / "src"
    link = link_dir / "link.py"
    os.symlink(outside, link)
    scope = parse_write_scope({"paths": ["src/**"], "mode": "allow"})

    with pytest.raises(FileServiceError) as excinfo:
        FileService().edit(
            path=link,
            old_string="outside",
            new_string="escaped",
            workspace_scope=str(ws),
            write_scope=scope,
        )

    assert excinfo.value.error_type == "write_scope_violation"
    assert "outside_scope" in excinfo.value.detail  # realpath 解析 symlink 后越界（FR-7）
    assert outside.read_bytes() == b"outside bytes\n"  # scope 外目标字节不变


def test_dotdot_traversal_and_absolute_escape_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    evil = _seed(tmp_path / "evil" / "x.py", "escaped\n")
    absolute_outside = _seed(tmp_path / "evil2" / "y.py", "absolute escape\n")
    scope = parse_write_scope({"paths": ["**"], "mode": "allow"})

    traversal = ws / "src" / ".." / ".." / "evil" / "x.py"
    with pytest.raises(FileServiceError) as excinfo:
        FileService().edit(
            path=traversal,
            old_string="escaped",
            new_string="in",
            workspace_scope=str(ws),
            write_scope=scope,
        )
    assert excinfo.value.error_type == "write_scope_violation"
    assert "outside_scope" in excinfo.value.detail
    assert evil.read_bytes() == b"escaped\n"

    with pytest.raises(FileServiceError) as excinfo:
        FileService().edit(
            path=absolute_outside,
            old_string="absolute escape",
            new_string="nope",
            workspace_scope=str(ws),
            write_scope=scope,
        )
    assert excinfo.value.error_type == "write_scope_violation"
    assert absolute_outside.read_bytes() == b"absolute escape\n"


# ── C7: edit_file 工具回执 ──


def test_edit_file_receipt_is_deterministic_failure_without_content_leak(
    tmp_path: Path,
) -> None:
    ws = _workspace(tmp_path)
    target = _seed(ws / "other" / "leak.txt", f"{SECRET}\nplain line\n")
    before = target.read_bytes()
    scope = parse_write_scope({"paths": ["src/**"], "mode": "allow"})
    tool = EditFileTool()

    ws_token = current_workspace_root.set(str(ws))
    scope_token = current_write_scope.set(scope)
    try:
        result = tool.run(
            {"path": str(target), "old_string": SECRET, "new_string": "nope"}
        )
    finally:
        current_write_scope.reset(scope_token)
        current_workspace_root.reset(ws_token)

    assert result.status.value == "failure"
    assert result.error_type == "write_scope_violation"
    content = result.content or ""
    assert content.startswith("该路径不在本子代理被允许写入的范围内")
    assert str(target) in content
    assert "src/**" in content
    assert "修正建议" in content
    assert SECRET not in content  # NFR-3: 回执不回显文件内容
    assert SECRET not in (result.error_detail or "")
    assert target.read_bytes() == before  # 拒绝零副作用
    assert write_scope_audit_snapshot()["violation_count"] == 1


def test_edit_file_scoped_write_within_pattern_succeeds(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    target = _seed(ws / "src" / "ok.py", "v = 1\n")
    scope = parse_write_scope({"paths": ["src/**"], "mode": "allow"})
    tool = EditFileTool()

    ws_token = current_workspace_root.set(str(ws))
    scope_token = current_write_scope.set(scope)
    try:
        result = tool.run(
            {"path": str(target), "old_string": "v = 1", "new_string": "v = 2"}
        )
    finally:
        current_write_scope.reset(scope_token)
        current_workspace_root.reset(ws_token)

    assert result.status.value == "success"
    assert target.read_bytes() == b"v = 2\n"
    assert str(target) in write_scope_audit_snapshot()["written_paths"]


def test_pattern_preview_truncated_at_ten_with_total_noted(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    target = _seed(ws / "other" / "t.py", "body\n")
    patterns = [f"pkg{i:02d}/**" for i in range(12)]
    scope = parse_write_scope({"paths": patterns, "mode": "allow"})

    with pytest.raises(FileServiceError) as excinfo:
        FileService().edit(
            path=target,
            old_string="body",
            new_string="x",
            workspace_scope=str(ws),
            write_scope=scope,
        )

    detail = excinfo.value.detail
    assert "共 12 条" in detail
    assert "仅显示前 10 条" in detail
    assert "pkg11/**" not in detail  # 第 11 条被截断
    assert "pkg09/**" in detail


# ── observe 判定（取舍：scope 同时约束读与写，fail-closed）──


def test_observe_enforced_with_same_error_type_and_audited(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    inside = _seed(ws / "src" / "readable.txt", "in scope\n")
    outside = _seed(ws / "other" / "unreadable.txt", f"{SECRET}\n")
    scope = parse_write_scope({"paths": ["src/**"], "mode": "allow"})
    service = _service(tmp_path, with_store=True)
    prov = FileArtifactProvenance(workspace_scope=str(ws), owner_session_id="t", operation_id="")

    with pytest.raises(FileServiceError) as excinfo:
        service.observe(
            path=outside,
            workspace_scope=str(ws),
            provenance=prov,
            write_scope=scope,
        )
    assert excinfo.value.error_type == "write_scope_violation"  # 同一 error_type
    assert "observe" in excinfo.value.detail  # detail 标明是 observe 路径
    assert SECRET not in excinfo.value.detail
    snapshot = write_scope_audit_snapshot()
    assert snapshot["violation_count"] == 1

    observed = service.observe(
        path=inside,
        workspace_scope=str(ws),
        provenance=prov,
        write_scope=scope,
    )
    assert observed.content == "in scope\n"  # scope 内照常读


def test_observe_with_empty_paths_scope_also_rejected(tmp_path: Path) -> None:
    """paths=[] 对显式传入 scope 的 observe 同样拒绝——统一 fail-closed 取舍的钉子.

    FR-4 的"只读子代理可读"由工具层接线保证（read_file 不传 write_scope，
    设计 C-list 仅 C7 接 edit_file）；此处钉的是 FileService 层的决定本身。
    """
    ws = _workspace(tmp_path)
    target = _seed(ws / "src" / "any.txt", "content\n")
    readonly_scope = parse_write_scope({"paths": [], "mode": "allow"})
    service = _service(tmp_path, with_store=True)
    prov = FileArtifactProvenance(workspace_scope=str(ws), owner_session_id="t", operation_id="")

    with pytest.raises(FileServiceError) as excinfo:
        service.observe(
            path=target,
            workspace_scope=str(ws),
            provenance=prov,
            write_scope=readonly_scope,
        )
    assert excinfo.value.error_type == "write_scope_violation"


# ── 边界：scoped edit 缺 workspace_scope = 调用方契约错误（既有 E5 家族）──


def test_scoped_edit_without_workspace_scope_is_contract_error(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    target = _seed(ws / "src" / "w.py", "w\n")
    scope = parse_write_scope({"paths": ["src/**"], "mode": "allow"})

    with pytest.raises(FileServiceError) as excinfo:
        FileService().edit(
            path=target,
            old_string="w",
            new_string="x",
            workspace_scope=None,
            write_scope=scope,
        )
    assert excinfo.value.error_type == "WorkspaceScopeMismatch"
    assert write_scope_audit_snapshot()["violation_count"] == 0  # 契约错误≠越界尝试
