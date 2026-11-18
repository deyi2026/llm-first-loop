"""M2-A（DESIGN-20261116 §3）：strict 锁 fail-closed + 锁内跨 Goal 路径冲突原子检查。

覆盖 §3.2-1 锁（fcntl 缺失 / flock OSError / 锁文件不可用）、§3.2-2 INV-1 配置
矩阵、§3.2-3 锁内检查（跨 Goal 确证 / 同 Goal 合法 / close 释放 / unknown
fail-closed）、§3.2-4 路径规则（绝对 / .. 逃逸 / symlink / 缺失 / 字面比较）、
§3.2-6 事件双事实、真实双进程并发。全部使用临时隔离 audit_dir——绝不在真实
data/audit 上开 enforce。BUG-09（v1.3 勘误）：close 不因现有重叠被拒。
"""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys
from pathlib import Path

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.lane import (
    Lane,
    LaneConstraintError,
    LanePathConflict,
    LanePathConflictUnknown,
    LaneStore,
    LaneStoreConfigError,
    LaneStoreLockUnavailable,
)


def _mkrepo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "a.md").write_text("a", encoding="utf-8")
    (repo / "src").mkdir(parents=True, exist_ok=True)
    return repo


def _strict(tmp_path: Path, *, repo_root: Path, enforce: bool = False) -> LaneStore:
    return LaneStore(
        tmp_path / "audit",
        lock_strict=True,
        enforce_cross_goal=enforce,
        repo_root=repo_root,
    )


def _create(store: LaneStore, *, goal_id: str, branch: str, paths: list[str]) -> Lane:
    return store.create(
        branch=branch,
        worktree=f"wt-{branch}",
        base_main_sha="deadbeef",
        goal_id=goal_id,
        paths=paths,
    )


# ---------------- §3.2-2 INV-1 / 配置矩阵 ----------------


def test_inv1_enforce_without_strict_rejected(tmp_path: Path) -> None:
    with pytest.raises(LaneStoreConfigError):
        LaneStore(tmp_path, lock_strict=False, enforce_cross_goal=True)


def test_matrix_default_off_legacy_fail_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """矩阵第 1 行：默认 warn 模式下 flock 失败仍 fail-open（历史行为不变）。"""

    def _boom(*_a, **_k):
        raise OSError("no flock")

    monkeypatch.setattr(fcntl, "flock", _boom)
    store = LaneStore(tmp_path)
    lane = _create(store, goal_id="G1", branch="b1", paths=["docs/a.md"])
    assert lane.paths == ["docs/a.md"]


def test_matrix_strict_lock_fail_rejects_create_update_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """矩阵第 3 行：strict 下锁不可用 → 三入口一致拒写（fail-closed）。"""

    def _boom(*_a, **_k):
        raise OSError("no flock")

    orig_flock = fcntl.flock
    monkeypatch.setattr(fcntl, "flock", _boom)
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo)
    with pytest.raises(LaneStoreLockUnavailable):
        _create(store, goal_id="G1", branch="b1", paths=["docs/a.md"])
    # 账本未被写入
    assert not (tmp_path / "audit" / "lanes.jsonl").exists()
    # 同一锁保护 update / close（预置一条 lane 再注入锁失败）
    monkeypatch.setattr(fcntl, "flock", orig_flock)
    lane = _create(store, goal_id="G1", branch="b1", paths=["docs/a.md"])
    monkeypatch.setattr(fcntl, "flock", _boom)
    with pytest.raises(LaneStoreLockUnavailable):
        store.update(lane.lane_id, expected_version=1, priority="hotfix")
    with pytest.raises(LaneStoreLockUnavailable):
        store.close(lane.lane_id, expected_version=1, status="closed", reason="r")


def test_matrix_enforce_lock_fail_no_degrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """矩阵第 5 行：enforce 下锁失败同样拒写，不降级为 warn 放行。"""

    def _boom(*_a, **_k):
        raise OSError("no flock")

    monkeypatch.setattr(fcntl, "flock", _boom)
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo, enforce=True)
    with pytest.raises(LaneStoreLockUnavailable):
        _create(store, goal_id="G1", branch="b1", paths=["docs/a.md"])


def test_strict_fcntl_import_error_rejects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """fcntl 缺失（sys.modules 置 None → import ImportError）时 strict 拒写。"""
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo)
    monkeypatch.setitem(sys.modules, "fcntl", None)
    with pytest.raises(LaneStoreLockUnavailable):
        _create(store, goal_id="G1", branch="b1", paths=["docs/a.md"])


def test_strict_lock_file_unwritable_rejects(tmp_path: Path) -> None:
    """锁文件不可写（audit 目录只读）→ strict 拒写；warn 模式维持放行。"""
    repo = _mkrepo(tmp_path)
    audit = tmp_path / "audit-ro"
    audit.mkdir()
    probe = audit / "lanes.jsonl.lock"
    probe.write_text("", encoding="utf-8")
    probe.chmod(0o444)
    store = LaneStore(audit, lock_strict=True, repo_root=repo)
    try:
        with pytest.raises(LaneStoreLockUnavailable):
            _create(store, goal_id="G1", branch="b1", paths=["docs/a.md"])
    finally:
        probe.chmod(0o644)


# ---------------- §3.2-3 锁内跨 Goal 检查 ----------------


def test_cross_goal_parent_child_enforce_rejected(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo, enforce=True)
    _create(store, goal_id="G1", branch="b1", paths=["docs/"])
    with pytest.raises(LanePathConflict) as ei:
        _create(store, goal_id="G2", branch="b2", paths=["docs/new.md"])
    assert ei.value.conflicts and ei.value.conflicts[0]["goal_id"] == "G1"
    assert "docs" in ei.value.conflicts[0]["shared"]


def test_cross_goal_conflict_writes_nothing(tmp_path: Path) -> None:
    """enforce 硬拒时主账本与事件流都不落（两个独立事实均未发生）。"""
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo, enforce=True)
    _create(store, goal_id="G1", branch="b1", paths=["docs/"])
    before = (tmp_path / "audit" / "lanes.jsonl").read_text(encoding="utf-8")
    events_before = (tmp_path / "audit" / "lane_events.jsonl").read_text(encoding="utf-8")
    with pytest.raises(LanePathConflict):
        _create(store, goal_id="G2", branch="b2", paths=["docs/new.md"])
    assert (tmp_path / "audit" / "lanes.jsonl").read_text(encoding="utf-8") == before
    assert (tmp_path / "audit" / "lane_events.jsonl").read_text(encoding="utf-8") == events_before


def test_same_goal_overlap_allowed_and_hinted(tmp_path: Path) -> None:
    """同 Goal main/sub/sub 合法并行拆分：不拒，仅 warn 提示。"""
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo, enforce=True)
    _create(store, goal_id="G1", branch="b-main", paths=["docs/"])
    sub = store.create(
        branch="b-sub",
        worktree="wt-b-sub",
        base_main_sha="deadbeef",
        goal_id="G1",
        lane_role="sub",
        paths=["docs/a.md"],
    )
    assert sub.lane_role == "sub"
    assert store.last_cross_goal_report["same_goal_overlaps"]


def test_close_releases_even_with_overlap_bug09(tmp_path: Path) -> None:
    """BUG-09：两条跨 Goal 重叠 lane 在途时 close 其一必须成功（释放不拒）。"""
    repo = _mkrepo(tmp_path)
    warm = LaneStore(tmp_path / "audit")  # 用默认账本铺两条重叠在途 lane
    a = _create(warm, goal_id="G1", branch="b1", paths=["docs/"])
    _create(warm, goal_id="G2", branch="b2", paths=["docs/deep/x.md"])
    strict = _strict(tmp_path, repo_root=repo, enforce=True)
    closed = strict.close(a.lane_id, expected_version=1, status="closed", reason="release")
    assert closed["status"] == "closed"
    # 释放后新占用可登记
    _create(strict, goal_id="G3", branch="b3", paths=["docs/deep/y.md"])


def test_other_goal_empty_paths_unknown_fail_closed(tmp_path: Path) -> None:
    """对方在途 paths=[]（如 lane-selftest-guard）→ unknown，enforce fail-closed
    拒写且不得表述为确证冲突（LanePathConflictUnknown ≠ LanePathConflict）。"""
    repo = _mkrepo(tmp_path)
    warm = LaneStore(tmp_path / "audit")
    _create(warm, goal_id="G-OTHER", branch="b-guard", paths=[])
    store = _strict(tmp_path, repo_root=repo, enforce=True)
    with pytest.raises(LanePathConflictUnknown) as ei:
        _create(store, goal_id="G2", branch="b2", paths=["src/main.py"])
    assert any("不可判定" in u["reason"] for u in ei.value.unknowns)


def test_other_goal_empty_paths_warn_only_hints(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    warm = LaneStore(tmp_path / "audit")
    _create(warm, goal_id="G-OTHER", branch="b-guard", paths=[])
    store = _strict(tmp_path, repo_root=repo, enforce=False)
    _create(store, goal_id="G2", branch="b2", paths=["src/main.py"])
    assert store.last_cross_goal_report["unknowns"]


def test_own_empty_paths_unknown_enforce(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo, enforce=True)
    with pytest.raises(LanePathConflictUnknown):
        _create(store, goal_id="G1", branch="b1", paths=[])


def test_disjoint_goal_paths_pass(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo, enforce=True)
    _create(store, goal_id="G1", branch="b1", paths=["docs/"])
    _create(store, goal_id="G2", branch="b2", paths=["src/"])  # 不重叠 → 放行
    _create(store, goal_id="G3", branch="b3", paths=["README.md"])


# ---------------- §3.2-4 路径规则 ----------------


def test_abs_path_inside_repo_normalized(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo)
    lane = _create(store, goal_id="G1", branch="b1", paths=[str(repo / "docs" / "a.md")])
    assert lane.paths == ["docs/a.md"]  # 存储值=归一结果（repo 根相对 POSIX）


def test_abs_path_outside_or_no_root_rejected(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo)
    with pytest.raises(LaneConstraintError):
        _create(store, goal_id="G1", branch="b1", paths=[str(tmp_path / "outside.md")])
    no_root = LaneStore(tmp_path / "audit2", lock_strict=True)
    with pytest.raises(LaneConstraintError):
        _create(no_root, goal_id="G1", branch="b1", paths=["/etc/passwd"])


def test_dotdot_escape_rejected_and_folded(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo)
    with pytest.raises(LaneConstraintError):
        _create(store, goal_id="G1", branch="b1", paths=["../escape.md"])
    with pytest.raises(LaneConstraintError):
        _create(store, goal_id="G1", branch="b1", paths=["docs/../../escape.md"])
    lane = _create(store, goal_id="G1", branch="b1", paths=["docs/../src/main.py"])
    assert lane.paths == ["src/main.py"]


def test_symlink_to_outside_rejected(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    (repo / "link-out").symlink_to(outside)
    store = _strict(tmp_path, repo_root=repo)
    with pytest.raises(LaneConstraintError):
        _create(store, goal_id="G1", branch="b1", paths=["link-out/file.md"])


def test_realpath_alias_conflict_best_effort(tmp_path: Path) -> None:
    """字面不同、symlink 指向同一目标 → realpath 辅助命中，标 best_effort。"""
    repo = _mkrepo(tmp_path)
    (repo / "alias").symlink_to(repo / "docs" / "a.md")
    warm = LaneStore(tmp_path / "audit")
    _create(warm, goal_id="G1", branch="b1", paths=["docs/a.md"])
    store = _strict(tmp_path, repo_root=repo)
    _create(store, goal_id="G2", branch="b2", paths=["alias"])
    conflicts = store.last_cross_goal_report["conflicts"]
    assert conflicts and conflicts[0]["best_effort"] is True


def test_nonexistent_path_literal_compare(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo, enforce=True)
    _create(store, goal_id="G1", branch="b1", paths=["never/exists.md"])
    with pytest.raises(LanePathConflict):  # 字面重叠（缺失路径允许声明、按字面比较）
        _create(store, goal_id="G2", branch="b2", paths=["never/exists.md/x.py"])


def test_backslash_and_bad_paths(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo)
    lane = _create(store, goal_id="G1", branch="b1", paths=["src\\win.py"])
    assert lane.paths == ["src/win.py"]
    with pytest.raises(LaneConstraintError):
        _create(store, goal_id="G1", branch="b2", paths=["bad\x00path"])


# ---------------- update 语义 ----------------


def test_update_paths_introducing_overlap_rejected(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo, enforce=True)
    a = _create(store, goal_id="G1", branch="b1", paths=["src/"])
    _create(store, goal_id="G2", branch="b2", paths=["docs/"])
    with pytest.raises(LanePathConflict):
        store.update(a.lane_id, expected_version=1, paths=["docs/x.md"])


def test_update_without_paths_not_rechecked(tmp_path: Path) -> None:
    """不带 paths 的状态推进不重复检查（占用未变）。"""
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo, enforce=True)
    a = _create(store, goal_id="G1", branch="b1", paths=["src/"])
    _create(store, goal_id="G2", branch="b2", paths=["docs/old.md"])  # G2 先占（不重叠）
    store.update(a.lane_id, expected_version=1, priority="hotfix")  # 不引入占用 → 放行


def test_update_excludes_self(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo, enforce=True)
    a = _create(store, goal_id="G1", branch="b1", paths=["docs/"])
    store.update(a.lane_id, expected_version=1, paths=["docs/a.md"])  # 与自身旧占用重叠 → 不拒


# ---------------- §3.2-6 事件双事实 ----------------


def test_event_append_failure_disclosed_strict(tmp_path: Path) -> None:
    """主账本成功 + 事件写失败 → 两个独立事实：不回滚、不谎称全成功。"""
    repo = _mkrepo(tmp_path)
    store = _strict(tmp_path, repo_root=repo)
    store._event_path = tmp_path / "audit" / "no-such-dir" / "lane_events.jsonl"
    lane = _create(store, goal_id="G1", branch="b1", paths=["docs/a.md"])
    rows = (tmp_path / "audit" / "lanes.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["lane_id"] == lane.lane_id
    assert store.last_event_append_failed is True


def test_legacy_store_unchanged_defaults(tmp_path: Path) -> None:
    """旧调用（只传 audit_dir）：宽松归一、无检查、绝对路径原样——行为不变。"""
    store = LaneStore(tmp_path)
    lane = _create(store, goal_id="G1", branch="b1", paths=["/abs/keep.md", "b\\c.py", "b\\c.py"])
    assert lane.paths == ["/abs/keep.md", "b/c.py"]
    assert store.last_cross_goal_report == {}


# ---------------- 真实双进程并发 ----------------


def test_two_processes_concurrent_create_single_winner(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path)
    audit = tmp_path / "audit"
    warm = LaneStore(audit)
    _create(warm, goal_id="G-SEED", branch="seed", paths=["unrelated/"])
    src_root = Path(__file__).resolve().parents[2] / "src"
    runner = tmp_path / "runner.py"
    runner.write_text(
        "\n".join(
            [
                "import sys",
                "sys.path.insert(0, sys.argv[1])",
                "from llm_loop.introspection.lane import LaneStore, LanePathConflict",
                "store = LaneStore(sys.argv[2], lock_strict=True, enforce_cross_goal=True, repo_root=sys.argv[5])",
                "try:",
                "    lane = store.create(branch='b-' + sys.argv[3], worktree='wt-' + sys.argv[3],",
                "                        base_main_sha='x', goal_id=sys.argv[3], paths=[sys.argv[4]])",
                "    print('OK', lane.lane_id)",
                "except LanePathConflict:",
                "    print('CONFLICT')",
                "    sys.exit(3)",
            ]
        ),
        encoding="utf-8",
    )
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    procs = [
        subprocess.Popen(
            [sys.executable, str(runner), str(src_root), str(audit), goal, "docs/concurrent.md", str(repo)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for goal in ("G-A", "G-B")
    ]
    codes = [p.wait(timeout=60) for p in procs]
    rows = [
        json.loads(line)
        for line in (audit / "lanes.jsonl").read_text(encoding="utf-8").strip().splitlines()
        if line
    ]
    winners = [r for r in rows if r["goal_id"] in {"G-A", "G-B"}]
    assert sorted(codes) == [0, 3]  # 恰一进程成功、另一进程确证冲突
    assert len(winners) == 1  # 账本恰一条新占用


# ---------------- 工具层接线（tools_lane.py 最小接线） ----------------


class _ToolHost:
    def __init__(self, audit_dir: Path, **kw) -> None:
        self.audit_dir = str(audit_dir)
        self.ctx = None
        for key, value in kw.items():
            setattr(self, key, value)


def _tool_open(host: _ToolHost, **kw):
    from llm_loop.introspection.tools_lane import run_lane_open

    args = {"branch": "fix/x", "worktree": "/tmp/wt-x", "goal_id": "goal-9", "paths": ["src/x.py"]}
    args.update(kw)
    return run_lane_open(None, host, args)


def test_tool_layer_default_host_unchanged(tmp_path: Path) -> None:
    """宿主未注入新属性 → 完全历史行为（默认构造，无检查）。"""
    host = _ToolHost(tmp_path)
    result = _tool_open(host)
    assert result.status is ToolResultStatus.SUCCESS


def test_tool_layer_enforce_conflict_reason_code(tmp_path: Path) -> None:
    from llm_loop.core.message import ToolResultStatus

    repo = _mkrepo(tmp_path)
    host = _ToolHost(
        tmp_path / "audit",
        lane_lock_strict=True,
        lane_enforce_cross_goal=True,
        lane_repo_root=str(repo),
    )
    assert _tool_open(host, branch="fix/a", paths=["docs/"]).status is ToolResultStatus.SUCCESS
    conflict = _tool_open(
        host, branch="fix/b", worktree="/tmp/wt-b", goal_id="goal-10", paths=["docs/new.md"]
    )
    assert conflict.status is ToolResultStatus.FAILURE
    assert "path_conflict" in conflict.content and "未写入" in conflict.content


def test_tool_layer_inv1_invalid_config(tmp_path: Path) -> None:
    from llm_loop.core.message import ToolResultStatus

    host = _ToolHost(tmp_path / "audit", lane_lock_strict=False, lane_enforce_cross_goal=True)
    result = _tool_open(host)
    assert result.status is ToolResultStatus.FAILURE
    assert "invalid_config" in result.content


def test_tool_layer_warn_diagnostics_rendered(tmp_path: Path) -> None:
    from llm_loop.core.message import ToolResultStatus

    repo = _mkrepo(tmp_path)
    warm = LaneStore(tmp_path / "audit")
    _create(warm, goal_id="goal-8", branch="fix/other", paths=["docs/"])
    host = _ToolHost(tmp_path / "audit", lane_lock_strict=True, lane_repo_root=str(repo))
    result = _tool_open(host, paths=["docs/a.md"])
    assert result.status is ToolResultStatus.SUCCESS
    assert "跨 Goal 路径重叠" in result.content


# ---------------- REVISE（2026-11-16 GPT-6 首轮核验 P1-A/B/C/D + P2）----------------


def test_p1c_enforce_without_repo_root_rejected_fail_fast(tmp_path: Path) -> None:
    """P1-C: enforce=true 且 repo_root 缺失 → 构造即拒。不得存在以字面比较
    代替根绑定的 enforce 实例（GPT-6 复现: symlink alias 双双放行）。warn 不受影响。"""
    with pytest.raises(LaneStoreConfigError):
        LaneStore(tmp_path / "audit-x", lock_strict=True, enforce_cross_goal=True)
    LaneStore(tmp_path / "audit-warn")  # 默认 warn 无 root 仍可用（历史行为）


def test_p1c_symlink_alias_with_root_still_rejected(tmp_path: Path) -> None:
    """P1-C 复现场景回归: repo 内 alias→docs symlink，G2 走别名声明同文件 →
    enforce 硬拒（有 repo_root 时 realpath 辅助必须命中）。"""
    repo = _mkrepo(tmp_path)
    (repo / "alias").symlink_to(repo / "docs", target_is_directory=True)
    store = LaneStore(
        tmp_path / "audit", lock_strict=True, enforce_cross_goal=True, repo_root=repo
    )
    _create(store, goal_id="G1", branch="b1", paths=["docs/a.md"])
    with pytest.raises(LanePathConflict):
        _create(store, goal_id="G2", branch="b2", paths=["alias/a.md"])


def _append_raw_lane_row(audit_dir: Path, row: dict) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    with (audit_dir / "lanes.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_p1d_legacy_escape_path_unknown_fail_closed(tmp_path: Path) -> None:
    """P1-D 复现（GPT-6）: 旧默认 store 落的在途 G1 paths=['../outside']
    （无法根绑定），strict+enforce+repo_root 新建 G2 → unknown fail-closed 拒写。"""
    repo = _mkrepo(tmp_path)
    legacy = tmp_path / "audit-legacy"
    warm = LaneStore(legacy)
    _create(warm, goal_id="G1", branch="b1", paths=["../outside"])
    store = LaneStore(
        legacy, lock_strict=True, enforce_cross_goal=True, repo_root=repo
    )
    with pytest.raises(LanePathConflictUnknown):
        _create(store, goal_id="G2", branch="b2", paths=["docs/a.md"])


def test_p1d_legacy_paths_not_a_list_unknown_fail_closed(tmp_path: Path) -> None:
    """P1-D: 旧账本 paths 非 list（字符串）→ unknown fail-closed。不得把字符串
    迭代成单字符路径参与比较后放行。"""
    repo = _mkrepo(tmp_path)
    audit = tmp_path / "audit-legacy2"
    _append_raw_lane_row(
        audit,
        {
            "lane_id": "lane-legacy1",
            "branch": "b1",
            "worktree": "wt-b1",
            "base_main_sha": "deadbeef",
            "goal_id": "G1",
            "paths": "docs",
            "status": "open",
            "version": 1,
        },
    )
    store = LaneStore(
        audit, lock_strict=True, enforce_cross_goal=True, repo_root=repo
    )
    with pytest.raises(LanePathConflictUnknown):
        _create(store, goal_id="G2", branch="b2", paths=["docs/a.md"])


def test_p1d_same_goal_legacy_overlap_still_hint_only(tmp_path: Path) -> None:
    """P1-D 边界: 同 Goal 合法重叠不连坐——unknown fail-closed 只作用跨 Goal。"""
    repo = _mkrepo(tmp_path)
    legacy = tmp_path / "audit-legacy3"
    warm = LaneStore(legacy)
    _create(warm, goal_id="G1", branch="b1", paths=["docs/a.md"])
    store = LaneStore(
        legacy, lock_strict=True, enforce_cross_goal=True, repo_root=repo
    )
    lane = store.create(
        goal_id="G1",
        branch="b2",
        worktree=str(tmp_path / "wt-b2"),
        base_main_sha="deadbeef",
        paths=["docs/a.md"],
        lane_role="sub",
    )
    assert lane is not None


def test_p2_append_lane_event_returns_real_false(tmp_path: Path) -> None:
    """P2: 事件文件不可写（目录占位 → OSError）→ append_lane_event 必须返回
    False，不得忽略 _append_event 的失败回执谎称成功（GPT-6 实测复现）。"""
    store = LaneStore(tmp_path / "audit")
    store._event_path.unlink(missing_ok=True)
    store._event_path.mkdir()
    assert store.append_lane_event("test_event", k="v") is False


def test_p1a_registry_exposes_lane_settings(tmp_path: Path) -> None:
    """P1-A: CorrectionToolRegistry 接受 lane_* 三参并经 RegistryHost 协议暴露；
    缺省全关（历史行为零回归）。"""
    from llm_loop.introspection.corrections import (
        CorrectionContext,
        CorrectionToolRegistry,
    )

    ctx = CorrectionContext()
    reg = CorrectionToolRegistry(ctx, audit_dir=tmp_path)
    assert reg.lane_lock_strict is False
    assert reg.lane_enforce_cross_goal is False
    assert reg.lane_repo_root in (None, "")

    reg2 = CorrectionToolRegistry(
        ctx,
        audit_dir=tmp_path,
        lane_lock_strict=True,
        lane_enforce_cross_goal=True,
        lane_repo_root="/repo-x",
    )
    assert reg2.lane_lock_strict is True
    assert reg2.lane_enforce_cross_goal is True
    assert reg2.lane_repo_root == "/repo-x"


def test_p1a_settings_env_parsing(tmp_path: Path) -> None:
    """P1-A: settings 三字段 env 解析（false/0 必须为 False，不存在 bool('false')）+ to_dict 可查。"""
    from llm_loop.config import load_settings

    _required = {
        "LLM_API_KEY": "test-key",
        "LLM_BASE_URL": "https://example.invalid/v1",
    }
    s_off = load_settings(
        {
            **_required,
            "LANE_LOCK_STRICT": "false",
            "LANE_ENFORCE_CROSS_GOAL": "0",
        }
    )
    assert s_off.lane_lock_strict is False
    assert s_off.lane_enforce_cross_goal is False
    assert s_off.lane_repo_root == ""

    s_on = load_settings(
        {
            **_required,
            "LANE_LOCK_STRICT": "true",
            "LANE_ENFORCE_CROSS_GOAL": "1",
            "LANE_REPO_ROOT": "/repo-x",
        }
    )
    assert s_on.lane_lock_strict is True
    assert s_on.lane_enforce_cross_goal is True
    assert s_on.lane_repo_root == "/repo-x"
    as_dict = s_on.to_status_dict()
    assert as_dict["lane_lock_strict"] is True
    assert as_dict["lane_enforce_cross_goal"] is True
    assert as_dict["lane_repo_root"] == "/repo-x"


def test_p1a_factory_passes_lane_settings(tmp_path: Path) -> None:
    """P1-A: 真实 factory 构造路径把 settings 三字段传入 registry（默认全关）。"""
    import inspect

    import llm_loop.factory as factory_mod

    src = inspect.getsource(factory_mod)
    assert "lane_lock_strict=" in src and "settings.lane_lock_strict" in src
    assert "lane_enforce_cross_goal=" in src
    assert "settings.lane_repo_root" in src


def test_p1b_queue_autosweep_strict_lock_unavailable_no_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-B: strict 宿主（lane_lock_strict=true）下 flock 失败 → queue auto-close
    fail-closed 不写账本，回执 closed=False 且如实披露；不谎称已关闭。"""

    def _boom(*_a, **_k):
        raise OSError("no flock")

    audit = tmp_path / "audit"
    warm = LaneStore(audit)
    live = _create(warm, goal_id="G1", branch="b1", paths=["docs/a.md"])
    rows_before = (audit / "lanes.jsonl").read_text(encoding="utf-8")

    monkeypatch.setattr(fcntl, "flock", _boom)  # 此后锁不可用
    from llm_loop.introspection.tools_merge_queue import _autosweep_lane_after_merge

    host = _ToolHost(audit, lane_lock_strict=True)
    result = _autosweep_lane_after_merge(
        host,
        {
            "lane_id": live.lane_id,
            "queue_id": "q1",
            "merge_commit": "c1",
        },
    )
    assert result.get("closed") is False
    assert result.get("note")
    assert (audit / "lanes.jsonl").read_text(encoding="utf-8") == rows_before


def test_p1b_queue_lanes_uses_host_lane_settings(tmp_path: Path) -> None:
    """P1-B/P1-A: merge queue _lanes 与 lane 工具入口同一配置源——宿主
    lane_* 属性生效（INV-1 非法配置显式抛，不静默降级为默认 warn）。"""
    from llm_loop.introspection.tools_merge_queue import _lanes

    audit = tmp_path / "audit-q"
    host_bad = _ToolHost(audit, lane_lock_strict=False, lane_enforce_cross_goal=True)
    with pytest.raises(LaneStoreConfigError):
        _lanes(host_bad)

    LaneStore(audit)  # 目录已建不影响
    host_strict = _ToolHost(
        audit, lane_lock_strict=True, lane_enforce_cross_goal=True, lane_repo_root=str(tmp_path)
    )
    store = _lanes(host_strict)
    assert store is not None
    assert store._lock_strict is True
    assert store._enforce_cross_goal is True

# ---------------- GPT-6 second adversarial review: P1-E/P1-F ----------------

@pytest.mark.parametrize("kind", ["missing", "file", "relative"])
def test_p1e_enforce_requires_existing_absolute_directory_root(tmp_path: Path, kind: str) -> None:
    """An invalid root cannot silently disable symlink alias detection."""
    if kind == "missing":
        root = tmp_path / "not-a-repository"
    elif kind == "file":
        root = tmp_path / "ordinary-file"
        root.write_text("x", encoding="utf-8")
    else:
        root = Path("relative-repo-root")
    with pytest.raises(LaneStoreConfigError):
        LaneStore(
            tmp_path / "audit-invalid-root",
            lock_strict=True,
            enforce_cross_goal=True,
            repo_root=root,
        )
    assert not (tmp_path / "audit-invalid-root" / "lanes.jsonl").exists()


@pytest.mark.parametrize("bad_paths", [[None], [""], ["  "], [123], ["docs/a.md", None]])
def test_p1f_legacy_nonstring_or_blank_path_unknown_fail_closed(
    tmp_path: Path, bad_paths: list[object]
) -> None:
    """Malformed legacy path elements must not be stringified into false disjoint claims."""
    repo = _mkrepo(tmp_path)
    audit = tmp_path / "audit"
    _create(LaneStore(audit), goal_id="G1", branch="legacy", paths=["placeholder"])
    ledger = audit / "lanes.jsonl"
    row = json.loads(ledger.read_text(encoding="utf-8"))
    row["paths"] = bad_paths
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
    before = ledger.read_bytes()
    store = LaneStore(audit, lock_strict=True, enforce_cross_goal=True, repo_root=repo)
    with pytest.raises(LanePathConflictUnknown):
        _create(store, goal_id="G2", branch="new", paths=["docs/a.md"])
    assert ledger.read_bytes() == before
