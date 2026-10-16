"""EVO-20261016-ac47e850: 声明式 git worktree 文件系统隔离单测。

覆盖：happy path、非 git 拒绝（不降级）、脏树保守保留、孤儿惰性回收、
上限拒绝、release 报告语义、SurfaceRequirements.fs_isolation 解析与矩阵 gap。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from llm_loop.core.execution_surface import (
    SurfaceRequirements,
    local_subagent_capability,
    validate_requirements,
)
from llm_loop.core.run_context import current_workspace_root
from llm_loop.workspace.worktree_isolation import (
    META_FILENAME,
    WorktreeIsolationError,
    format_release_note,
    prepare_worktree,
    release_worktree,
)


def _git(cwd: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, f"git {args}: {proc.stderr}"
    return proc.stdout.strip()


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(str(repo), "init", "-q")
    _git(str(repo), "config", "user.email", "t@t")
    _git(str(repo), "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed", encoding="utf-8")
    _git(str(repo), "add", "-A")
    _git(str(repo), "commit", "-q", "-m", "seed")
    return repo


class TestPrepare:
    def test_happy_path_creates_worktree_with_meta(self, git_repo: Path) -> None:
        lease = prepare_worktree("lfl-subagent-abcdef12", parent_root=str(git_repo))
        wt = Path(lease.path)
        assert wt.is_dir()
        assert wt.name.startswith("lfl-child-")
        meta = json.loads((wt / META_FILENAME).read_text("utf-8"))
        assert meta["child_id"] == "lfl-subagent-abcdef12"
        assert lease.parent_root == str(git_repo.resolve())

    def test_non_git_workspace_refused_with_reason_code(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(WorktreeIsolationError) as ei:
            prepare_worktree("lfl-subagent-11111111", parent_root=str(plain))
        assert ei.value.reason_code == "NOT_GIT_WORKSPACE"

    def test_disk_low_refused(self, git_repo: Path, monkeypatch) -> None:
        import llm_loop.workspace.worktree_isolation as mod

        monkeypatch.setattr(
            mod.shutil, "disk_usage", lambda p: type("D", (), {"free": 1})()
        )
        with pytest.raises(WorktreeIsolationError) as ei:
            prepare_worktree("lfl-subagent-22222222", parent_root=str(git_repo))
        assert ei.value.reason_code == "DISK_LOW"

    def test_existing_dir_refused(self, git_repo: Path) -> None:
        target = git_repo / ".worktrees" / "lfl-child-33333333"
        target.mkdir(parents=True)
        with pytest.raises(WorktreeIsolationError) as ei:
            prepare_worktree("lfl-subagent-33333333", parent_root=str(git_repo))
        assert ei.value.reason_code == "WORKTREE_LIMIT"

    def test_dirty_orphans_over_limit_refuse_new(self, git_repo: Path) -> None:
        for i in range(3):
            lease = prepare_worktree(f"lfl-subagent-dirty{i:08d}", parent_root=str(git_repo))
            (Path(lease.path) / f"untracked{i}.txt").write_text("x", encoding="utf-8")
            # 脏孤儿：meta 老化 + 全树 mtime 老化（活性代理视其为死树）。
            meta_p = Path(lease.path) / META_FILENAME
            meta = json.loads(meta_p.read_text("utf-8"))
            meta["created_at"] = time.time() - 48 * 3600
            meta_p.write_text(json.dumps(meta), encoding="utf-8")
            old = time.time() - 48 * 3600
            for f in Path(lease.path).rglob("*"):
                os.utime(f, (old, old))
        with pytest.raises(WorktreeIsolationError) as ei:
            prepare_worktree(
                "lfl-subagent-99999999",
                parent_root=str(git_repo),
                max_kept_dirty=3,
            )
        assert ei.value.reason_code == "WORKTREE_LIMIT"

    def test_clean_orphan_swept_and_spawn_ok(self, git_repo: Path) -> None:
        lease_old = prepare_worktree("lfl-subagent-old111111", parent_root=str(git_repo))
        meta_p = Path(lease_old.path) / META_FILENAME
        meta = json.loads(meta_p.read_text("utf-8"))
        meta["created_at"] = time.time() - 48 * 3600
        meta_p.write_text(json.dumps(meta), encoding="utf-8")
        lease_new = prepare_worktree("lfl-subagent-new111111", parent_root=str(git_repo))
        assert not Path(lease_old.path).exists()
        assert Path(lease_new.path).is_dir()

    def test_unmanaged_dirs_never_touched(self, git_repo: Path) -> None:
        unrelated = git_repo / ".worktrees" / "drill-manual-tree"
        unrelated.mkdir(parents=True)
        (unrelated / "keep.txt").write_text("keep", encoding="utf-8")
        prepare_worktree("lfl-subagent-44444444", parent_root=str(git_repo))
        assert (unrelated / "keep.txt").exists()

    def test_empty_parent_root_refused(self) -> None:
        with pytest.raises(WorktreeIsolationError) as ei:
            prepare_worktree("lfl-subagent-55555555", parent_root="")
        assert ei.value.reason_code == "NO_WORKSPACE_ROOT"

    def test_tag_injection_falls_back_to_hash(self, git_repo: Path) -> None:
        lease = prepare_worktree("lfl-subagent-../../evil", parent_root=str(git_repo))
        wt = Path(lease.path)
        assert wt.parent.name == ".worktrees"  # 无路径逃逸
        assert wt.is_dir()


class TestRelease:
    def test_clean_tree_removed(self, git_repo: Path) -> None:
        lease = prepare_worktree("lfl-subagent-rel111111", parent_root=str(git_repo))
        report = release_worktree(lease.parent_root, lease.path)
        assert report.state == "removed"
        assert not Path(lease.path).exists()

    def test_committed_detached_head_kept_with_head(self, git_repo: Path) -> None:
        """P1-1: child 在 detached HEAD 上 commit 后工作区'干净'，但产出在提交里——
        必须判脏保留并附 HEAD hash，不得强删。"""
        lease = prepare_worktree("lfl-subagent-cmt111111", parent_root=str(git_repo))
        wt = Path(lease.path)
        (wt / "new_work.txt").write_text("child 产出", encoding="utf-8")
        _git(str(wt), "add", "-A")
        _git(str(wt), "commit", "-q", "-m", "child work")
        report = release_worktree(lease.parent_root, lease.path)
        assert report.state == "kept_dirty"
        assert report.head  # 附 HEAD hash
        assert wt.is_dir()  # 提交未被销毁
        note = format_release_note(report, lease.path)
        assert report.head in note

    def test_ignored_files_kept_not_deleted(self, git_repo: Path) -> None:
        """P1-2: 命中 .gitignore 的产物对 --porcelain 不可见，必须判脏保留。"""
        (git_repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
        _git(str(git_repo), "add", ".gitignore")
        _git(str(git_repo), "commit", "-q", "-m", "gitignore")
        lease = prepare_worktree("lfl-subagent-ign111111", parent_root=str(git_repo))
        wt = Path(lease.path)
        (wt / "run.log").write_text("ignored artifact", encoding="utf-8")
        report = release_worktree(lease.parent_root, lease.path)
        assert report.state == "kept_dirty"
        assert (wt / "run.log").exists()  # ignored 文件未被强删

    def test_dirty_tree_kept_not_deleted(self, git_repo: Path) -> None:
        lease = prepare_worktree("lfl-subagent-rel222222", parent_root=str(git_repo))
        (Path(lease.path) / "dirty.txt").write_text("改动", encoding="utf-8")
        report = release_worktree(lease.parent_root, lease.path)
        assert report.state == "kept_dirty"
        assert report.dirty_files == 1
        assert Path(lease.path).exists()  # 未合并改动不被自动删除

    def test_note_mentions_explicit_merge(self, git_repo: Path) -> None:
        lease = prepare_worktree("lfl-subagent-rel333333", parent_root=str(git_repo))
        (Path(lease.path) / "d.txt").write_text("x", encoding="utf-8")
        report = release_worktree(lease.parent_root, lease.path)
        note = format_release_note(report, lease.path)
        assert "未自动合并" in note
        assert "显式处理" in note

    def test_missing_path_reported(self, git_repo: Path) -> None:
        report = release_worktree(str(git_repo), str(git_repo / ".worktrees" / "nope"))
        assert report.state == "missing"


class TestSurfaceDeclaration:
    def test_requirements_parse_fs_isolation(self) -> None:
        reqs = SurfaceRequirements.from_kwargs(
            {"fs": True, "fs_isolation": True}
        )
        assert reqs.fs_isolation is True
        assert reqs.declared() is True
        empty = SurfaceRequirements.from_kwargs({})
        assert empty.fs_isolation is False
        assert empty.declared() is False

    def test_local_surface_accepts_fs_isolation(self) -> None:
        reqs = SurfaceRequirements.from_kwargs({"fs": True, "fs_isolation": True})
        gaps = validate_requirements(
            local_subagent_capability({"execute_command", "edit_file", "read_file"}),
            reqs,
        )
        assert gaps == []

    def test_fs_isolation_without_fs_tools_still_gap(self) -> None:
        from llm_loop.core.execution_surface import SurfaceCapability

        nofs = SurfaceCapability(
            surface="local_subagent",
            allowed_tools=(),
            tool_enumeration="registry",
            network_egress=False,
            filesystem_scope="none",
            session_continuity=False,
        )
        reqs = SurfaceRequirements.from_kwargs({"fs_isolation": True})
        gaps = validate_requirements(nofs, reqs)
        assert any("fs_isolation" in g for g in gaps)

    def test_nonlocal_surface_rejects_fs_isolation(self) -> None:
        from llm_loop.core.execution_surface import SurfaceCapability

        codearts = SurfaceCapability(
            surface="codearts",
            allowed_tools=None,
            tool_enumeration="remote_defined",
            network_egress=True,
            filesystem_scope="remote_sandbox",
            session_continuity=True,
        )
        reqs = SurfaceRequirements.from_kwargs({"fs_isolation": True})
        gaps = validate_requirements(codearts, reqs)
        assert any("fs_isolation" in g and "不支持" in g for g in gaps)


class TestIsolationSemantics:
    """P2-4: 隔离有效性的模块级语义——current_workspace_root 指向 worktree 后，
    工具面派生路径落 worktree；session/journal 落盘不随之漂移；父上下文不受影响。"""

    def test_workspace_base_follows_contextvar_into_worktree(
        self, git_repo: Path
    ) -> None:
        from llm_loop.core.run_context import current_workspace_root

        lease = prepare_worktree("lfl-subagent-iso111111", parent_root=str(git_repo))
        parent_val = current_workspace_root.get()

        def _child_view() -> str:
            return current_workspace_root.get()

        tok = current_workspace_root.set(lease.path)
        try:
            inside = _child_view()
        finally:
            current_workspace_root.reset(tok)
        assert Path(inside).resolve() == Path(lease.path).resolve()
        assert current_workspace_root.get() == parent_val  # 父不受影响
        release_worktree(lease.parent_root, lease.path)

    def test_journal_root_not_derived_from_workspace_root(self) -> None:
        """journal 落盘由 session_store 决定；workspace_root 只做 effect 归属判定。"""
        import inspect

        from llm_loop.core import tool_execution_journal as tej

        src = inspect.getsource(tej.ToolExecutionJournal.__init__)
        assert "session_store" in src
        assert "workspace_root" not in src  # 构造不消费 workspace_root

    def test_meta_deleted_child_kept_dirty(self, git_repo: Path) -> None:
        """P1 复审修复: child git clean 掉 meta 后，树必须判脏保留而非强删。"""
        lease = prepare_worktree("lfl-subagent-cln111111", parent_root=str(git_repo))
        wt = Path(lease.path)
        (wt / "work.txt").write_text("产出", encoding="utf-8")
        _git(str(wt), "add", "work.txt")  # 只加产出，不加 meta
        _git(str(wt), "commit", "-q", "-m", "child work")
        _git(str(wt), "clean", "-fdq")  # 删掉未跟踪 meta
        assert not (wt / ".lfl-worktree.json").exists()
        report = release_worktree(lease.parent_root, lease.path)
        assert report.state == "kept_dirty"  # 无法证明安全 → 保留
        assert wt.is_dir()


class TestRunnerIntegration:
    """P2-1（六审）: start() 级集成——拒绝路径 reason_code 原样透出、
    正常路径 child 在隔离树施工且终态保守保留（不自动合并）。"""

    def _runner(self, llm, root: Path):  # noqa: ANN001
        from llm_loop.core.session import SessionStore
        from llm_loop.event_log.store import EventStore
        from llm_loop.subagent.runner import SubAgentRunner
        from llm_loop.tools.registry import ToolRegistry

        events = EventStore(root / "events", enabled=True)
        sessions = SessionStore(root / "sessions", event_store=events)
        return SubAgentRunner(
            llm=llm, registry=ToolRegistry(), session_store=sessions
        )  # type: ignore[arg-type]

    def test_start_refuses_non_git_workspace_with_reason_code(
        self, tmp_path: Path
    ) -> None:
        from llm_loop.core.run_context import current_session_id

        class _LLM:
            def chat(self, *a, **k):  # noqa: ANN002, ANN003
                raise AssertionError("child 不应启动")

        runner = self._runner(_LLM(), tmp_path)
        plain = tmp_path / "plain_ws"
        plain.mkdir()
        tok = current_session_id.set("parent-iso-refuse")
        ws_tok = current_workspace_root.set(str(plain.resolve()))
        try:
            started = runner.start(
                "needs isolation", depth=0, fs_isolation=True
            )
        finally:
            current_workspace_root.reset(ws_tok)
            current_session_id.reset(tok)
        assert started["accepted"] is False
        assert "NOT_GIT_WORKSPACE" in str(started.get("detail", ""))

    def test_start_dirty_child_keeps_worktree(self, git_repo: Path) -> None:
        from llm_loop.core.message import ToolCall
        from llm_loop.core.run_context import current_session_id
        from llm_loop.llm.client import LLMResponse

        class _WriteLLM:
            def __init__(self) -> None:
                self.calls = 0

            def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
                self.calls += 1
                if self.calls == 1:
                    return LLMResponse(
                        content="",
                        tool_calls=[
                            ToolCall(
                                id="child-touch",
                                name="edit_file",
                                arguments={
                                    "path": "seed.txt",
                                    "old_string": "seed",
                                    "new_string": "child 产出",
                                },
                            )
                        ],
                        provider="fake",
                    )
                return LLMResponse(
                    content="child done", tool_calls=[], provider="fake"
                )

        from llm_loop.tools.builtin.edit_file import EditFileTool
        from llm_loop.tools.registry import ToolRegistry

        class _Runner:
            pass

        # 需要真实 edit_file 工具 → 重建 runner 带 registry
        from llm_loop.core.session import SessionStore
        from llm_loop.event_log.store import EventStore
        from llm_loop.subagent.runner import SubAgentRunner

        events = EventStore(git_repo / "wt-events", enabled=True)
        sessions = SessionStore(git_repo / "wt-sessions", event_store=events)
        registry = ToolRegistry()
        registry.register(EditFileTool())
        runner = SubAgentRunner(
            llm=_WriteLLM(), registry=registry, session_store=sessions
        )  # type: ignore[arg-type]

        tok = current_session_id.set("parent-iso-ok")
        ws_tok = current_workspace_root.set(str(git_repo.resolve()))
        try:
            started = runner.start(
                "write in isolation", depth=0, fs_isolation=True
            )
            assert started["accepted"] is True
            worktree = str(started.get("worktree", ""))
            assert worktree and "lfl-child-" in worktree
            deadline = time.monotonic() + 15.0
            snapshot: dict = {}
            while time.monotonic() < deadline:
                ok, _d, snapshot = runner.result_current(
                    started["child_id"], wait_seconds=0.2
                )
                assert ok
                if snapshot.get("state") != "running":
                    break
            assert snapshot.get("state") not in ("running", None)
            _res = snapshot.get("result")
            final = str(
                getattr(_res, "final_answer", None)
                or snapshot.get("final_answer")
                or ""
            )
            assert "[worktree] 隔离树保留" in final
            assert Path(worktree).is_dir()  # 脏树不被自动删除
            assert (Path(worktree) / "seed.txt").read_text("utf-8") == "child 产出"
            assert (git_repo / "seed.txt").read_text("utf-8") == "seed"  # 父不被污染
        finally:
            current_workspace_root.reset(ws_tok)
            current_session_id.reset(tok)
