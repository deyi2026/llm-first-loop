"""archive-stale 批量归档命令（CLI 薄壳）口径测试.

覆盖: 阈值边界（±30s 容差两侧，默认 5 天）、pinned/未过期不进候选、dry-run 零变更、
归档 + shared_current 指针清理 + 幂等重跑、busy 跳过、身份冲突跳过、多工作区遍历、
--days 覆盖。
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import llm_loop.cli as cli
from llm_loop.core.session import SessionStore
from llm_loop.timekeeping import system_local_now
from llm_loop.workspace.store import WorkspaceStore

TOLERANCE = timedelta(seconds=30)


def _root(data_dir: Path) -> Path:
    return data_dir / "sessions"


def _part(data_dir: Path, partition: str = "") -> Path:
    return _root(data_dir) / partition if partition else _root(data_dir)


def _make_session(data_dir: Path, partition: str = "", *, age: timedelta,
                  title: str = "旧会话", pinned: bool = False) -> str:
    """在指定分区创建 active 会话，并把 updated_at 改写为 now - age."""
    part = _part(data_dir, partition)
    part.mkdir(parents=True, exist_ok=True)
    store = SessionStore(part, identity_root=_root(data_dir))
    sid = store.create()
    p = part / f"{sid}.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["updated_at"] = (system_local_now() - age).isoformat(timespec="microseconds")
    data["title"] = title
    data["pinned"] = pinned
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return sid


def _status(data_dir: Path, sid: str, partition: str = "") -> str:
    return json.loads((_part(data_dir, partition) / f"{sid}.json").read_text(encoding="utf-8"))["status"]


def _run(data_dir: Path, *extra: str) -> tuple[int, list[dict]]:
    rc = cli.main(["archive-stale", "--data-dir", str(data_dir), *extra])
    reports = sorted((data_dir / "reports" / "archive_stale").glob("*.jsonl"))
    assert reports, "应生成 jsonl 报告文件"
    rows = [json.loads(line) for line in reports[-1].read_text(encoding="utf-8").splitlines()]
    return rc, rows


def test_boundary_pins_and_dry_run_zero_mutation(tmp_path):
    data_dir = tmp_path / "data"
    stale = _make_session(data_dir, age=timedelta(days=5) + TOLERANCE, title="过期")
    exact = _make_session(data_dir, age=timedelta(days=5) - TOLERANCE, title="恰好未过期")
    fresh = _make_session(data_dir, age=timedelta(days=1), title="新会话")
    pinned = _make_session(data_dir, age=timedelta(days=30), title="置顶", pinned=True)

    rc, rows = _run(data_dir, "--dry-run")
    assert rc == 0
    assert [r["session_id"] for r in rows] == [stale]
    assert rows[0]["action"] == "dry-run"
    assert rows[0]["title"] == "过期"
    assert all(_status(data_dir, sid) == "active" for sid in (stale, exact, fresh, pinned))


def test_archive_pointer_cleanup_and_idempotent_rerun(tmp_path):
    data_dir = tmp_path / "data"
    sid = _make_session(data_dir, age=timedelta(days=6))
    store = SessionStore(_root(data_dir), identity_root=_root(data_dir))
    store.set_shared_current(sid)
    assert store.get_shared_current() == sid

    rc, rows = _run(data_dir)
    assert rc == 0
    assert rows[0]["action"] == "archived"
    assert _status(data_dir, sid) == "archived"
    assert store.get_shared_current() is None  # 指针已随归档清理

    rc2, rows2 = _run(data_dir)  # 幂等重跑：archived 不再命中
    assert rc2 == 0
    assert rows2 == []


def test_busy_session_skipped_not_archived(tmp_path):
    data_dir = tmp_path / "data"
    sid = _make_session(data_dir, age=timedelta(days=6))
    owner = SessionStore(_root(data_dir), identity_root=_root(data_dir))
    with owner.run_lease(sid):
        rc, rows = _run(data_dir)
    assert rc == 0  # busy 是跳过，不是失败
    assert rows[0]["action"] == "busy"
    assert _status(data_dir, sid) == "active"


def test_identity_conflict_skipped(tmp_path):
    data_dir = tmp_path / "data"
    sid = _make_session(data_dir, age=timedelta(days=6))
    owner_file = next(p for p in _root(data_dir).rglob(f"{sid}.json") if p.parent.name == ".identity")
    owner_file.write_text(
        json.dumps({"owner": "other-workspace", "claimed_at": "2020-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    rc, rows = _run(data_dir)
    assert rc == 0
    assert rows[0]["action"] == "identity_conflict"
    assert _status(data_dir, sid) == "active"


def test_multi_workspace_partitions(tmp_path):
    data_dir = tmp_path / "data"
    (tmp_path / "ws_a").mkdir()
    (tmp_path / "ws_b").mkdir()
    ws = WorkspaceStore(data_dir)
    a, b = ws.register(tmp_path / "ws_a"), ws.register(tmp_path / "ws_b")
    sid_a = _make_session(data_dir, a.id, age=timedelta(days=7), title="A旧")
    sid_b = _make_session(data_dir, b.id, age=timedelta(days=1), title="B新")

    rc, rows = _run(data_dir)
    assert rc == 0
    assert [r["session_id"] for r in rows] == [sid_a]
    assert rows[0]["workspace"] == a.id
    assert _status(data_dir, sid_a, a.id) == "archived"
    assert _status(data_dir, sid_b, b.id) == "active"


def test_days_option_overrides_default(tmp_path):
    data_dir = tmp_path / "data"
    sid = _make_session(data_dir, age=timedelta(days=3))
    rc, rows = _run(data_dir, "--dry-run")  # 默认 5 天：3 天未过期
    assert rc == 0
    assert rows == []
    rc, rows = _run(data_dir, "--days", "2", "--dry-run")
    assert rc == 0
    assert [r["session_id"] for r in rows] == [sid]
