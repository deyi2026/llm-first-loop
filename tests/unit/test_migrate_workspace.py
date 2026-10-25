"""P1-3 §7.6: migrate_workspace 核心逻辑单元测试（tmp 假数据，绝不触真实 data/）.

假数据布局：伪造 sessions/<旧键>/ 分区、.identity 账本、工件记录桶、
WorkspaceStore 注册表小样本 + 一个其它分区（research 语义）。六项校验：
改名计数、identity 改写、注册表切换、冲突注入、幂等重跑、current 断言。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from llm_loop.workspace.artifacts import _workspace_bucket, workspace_scope
from llm_loop.workspace.store import (
    WorkspaceMigrationConflictError,
    WorkspaceStore,
    workspace_key,
)

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import migrate_workspace as mw  # noqa: E402  — scripts 层模块（sys.path 注入后导入）


@pytest.fixture
def fake_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """tmp 假数据小样本：旧/新根 + 分区/账本/桶/注册表/其它分区."""
    old_root = tmp_path / "fake-code-root"
    new_root = tmp_path / "fake-home" / "lfl-workspace"
    old_root.mkdir()
    (tmp_path / "fake-home").mkdir()
    data_dir = tmp_path / "data"
    old_key = workspace_key(old_root)
    new_key = workspace_key(new_root)
    old_bucket = _workspace_bucket(workspace_scope(old_root))
    new_bucket = _workspace_bucket(workspace_scope(new_root))

    # sessions 分区：两个会话目录 + 各一个 jsonl 文件
    partition = data_dir / "sessions" / old_key / "2026" / "10" / "25"
    partition.mkdir(parents=True)
    (partition / "sess-a.jsonl").write_text('{"sid":"a","turn":1}\n', encoding="utf-8")
    (partition / "sess-b.jsonl").write_text('{"sid":"b","turn":1}\n', encoding="utf-8")
    # 其它分区（迁移不得触碰）
    other = data_dir / "sessions" / "research-other" / "note.txt"
    other.parent.mkdir(parents=True)
    other.write_text("untouched", encoding="utf-8")
    # .identity 账本：两个旧 owner + 一个其它 owner
    identity = data_dir / "sessions" / ".identity"
    identity.mkdir(parents=True)
    (identity / "sess-a.json").write_text(
        f'{{"owner": "{old_key}", "claimed_at": "2026-10-25T08:00:00"}}', encoding="utf-8"
    )
    (identity / "sess-b.json").write_text(
        f'{{"owner": "{old_key}", "claimed_at": "2026-10-25T08:01:00"}}', encoding="utf-8"
    )
    (identity / "sess-c.json").write_text(
        '{"owner": "research-other", "claimed_at": "2026-10-25T07:00:00"}', encoding="utf-8"
    )
    # 工件记录桶：两条 record
    bucket = data_dir / "artifacts" / "records" / old_bucket / "2026"
    bucket.mkdir(parents=True)
    (bucket / "r1.json").write_text('{"id":"r1","canonical_path":"/x"}', encoding="utf-8")
    (bucket / "r2.json").write_text('{"id":"r2","canonical_path":"/y"}', encoding="utf-8")
    # 注册表：旧根已注册且为 current
    monkeypatch.setenv("LFL_WORKSPACE_ALLOWED_ROOTS", str(tmp_path))
    WorkspaceStore(data_dir).register_and_switch(str(old_root))

    return {
        "tmp_path": tmp_path,
        "old_root": old_root,
        "new_root": new_root,
        "data_dir": data_dir,
        "old_key": old_key,
        "new_key": new_key,
        "old_bucket": old_bucket,
        "new_bucket": new_bucket,
        "expected_files": 2,
        "expected_bytes": (partition / "sess-a.jsonl").stat().st_size
        + (partition / "sess-b.jsonl").stat().st_size,
    }


def _run_migration(layout: dict, *, audit_path: Path | None = None) -> dict:
    audit = mw.AuditLog(audit_path or layout["tmp_path"] / "audit" / "test-audit.json")
    return mw.run_core_migration(
        layout["data_dir"],
        old_key=layout["old_key"],
        new_key=layout["new_key"],
        old_bucket=layout["old_bucket"],
        new_bucket=layout["new_bucket"],
        new_root=layout["new_root"],
        audit=audit,
    )


# 1) 改名计数
def test_rename_partition_counts_and_atomicity(fake_layout: dict) -> None:
    sessions_root = fake_layout["data_dir"] / "sessions"
    result = mw.rename_sessions_partition(sessions_root, fake_layout["old_key"], fake_layout["new_key"])
    assert result["action"] == "renamed"
    assert result["files"] == fake_layout["expected_files"]
    assert result["bytes"] == fake_layout["expected_bytes"]
    assert not (sessions_root / fake_layout["old_key"]).exists()  # 源消失（改名而非复制）
    assert (sessions_root / fake_layout["new_key"] / "2026" / "10" / "25").is_dir()
    # 其它分区不受影响
    assert (sessions_root / "research-other" / "note.txt").read_text(encoding="utf-8") == "untouched"


# 2) identity 改写（含 claimed_at 保留 + 其它 owner 不动 + 幂等）
def test_identity_owner_rewrite(fake_layout: dict) -> None:
    identity = fake_layout["data_dir"] / "sessions" / ".identity"
    result = mw.rewrite_identity_owners(identity, fake_layout["old_key"], fake_layout["new_key"])
    assert result["scanned"] == 3 and result["rewritten"] == 2
    a = result and __import__("json").loads((identity / "sess-a.json").read_text(encoding="utf-8"))
    assert a["owner"] == fake_layout["new_key"]
    assert a["claimed_at"] == "2026-10-25T08:00:00"  # 时间戳保留
    c = __import__("json").loads((identity / "sess-c.json").read_text(encoding="utf-8"))
    assert c["owner"] == "research-other"
    # 幂等：重跑改写计数归零
    second = mw.rewrite_identity_owners(identity, fake_layout["old_key"], fake_layout["new_key"])
    assert second["rewritten"] == 0


# 3) 注册表切换
def test_registry_switch(fake_layout: dict) -> None:
    data_dir = fake_layout["data_dir"]
    fake_layout["new_root"].mkdir(parents=True, exist_ok=True)  # 生产序：run_core_migration 步骤1先建根
    store = WorkspaceStore(data_dir)
    old_entries = {w.id for w in store.list()}
    result = mw.switch_registry(data_dir, fake_layout["new_root"])
    assert result["action"] == "switched"
    assert result["current"] == fake_layout["new_key"]
    store = WorkspaceStore(data_dir)  # 重开实例回读磁盘（get_current 读内存快照）
    current = store.get_current()
    assert current is not None and current.id == fake_layout["new_key"]
    assert current.path == str(fake_layout["new_root"])
    assert fake_layout["old_key"] in old_entries  # 旧条目保留在注册表
    assert fake_layout["old_key"] in {w.id for w in store.list()}
    # 幂等：重跑不再切换
    again = mw.switch_registry(data_dir, fake_layout["new_root"])
    assert again["action"] == "already_current"


# 4) 冲突注入（同名异内容 / 文件集不一致）
def test_conflict_injection_same_name_different_bytes(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    (sessions / "old").mkdir(parents=True)
    (sessions / "new").mkdir(parents=True)
    (sessions / "old" / "f.json").write_text("A", encoding="utf-8")
    (sessions / "new" / "f.json").write_text("B", encoding="utf-8")
    with pytest.raises(WorkspaceMigrationConflictError, match="内容不同"):
        mw.rename_sessions_partition(sessions, "old", "new")


def test_conflict_injection_file_set_mismatch(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    (sessions / "old").mkdir(parents=True)
    (sessions / "new").mkdir(parents=True)
    (sessions / "old" / "a.json").write_text("A", encoding="utf-8")
    (sessions / "new" / "b.json").write_text("B", encoding="utf-8")
    with pytest.raises(WorkspaceMigrationConflictError, match="文件集不一致"):
        mw.rename_sessions_partition(sessions, "old", "new")


def test_conflict_injection_artifact_bucket(tmp_path: Path) -> None:
    records = tmp_path / "records"
    (records / "ob").mkdir(parents=True)
    (records / "nb").mkdir(parents=True)
    (records / "ob" / "r.json").write_text("1", encoding="utf-8")
    (records / "nb" / "r.json").write_text("2", encoding="utf-8")
    with pytest.raises(WorkspaceMigrationConflictError, match="工件记录桶冲突"):
        mw.copy_artifact_records(records, "ob", "nb")


# 5+6) 幂等重跑 + current 断言（全链路核心函数连跑）
def test_full_migration_idempotent_and_current(fake_layout: dict) -> None:
    data_dir = fake_layout["data_dir"]
    sessions = data_dir / "sessions"
    # 第一遍：改名/改写/复制/切换全部执行
    first = _run_migration(fake_layout)
    assert first["rename_sessions_partition"]["action"] == "renamed"
    assert first["rewrite_identity_owners"]["rewritten"] == 2
    assert first["copy_artifact_records"]["copied"] == 2
    assert first["switch_registry"]["action"] == "switched"
    # current 断言：指向新根
    current = WorkspaceStore(data_dir).get_current()
    assert current is not None
    assert Path(current.path) == fake_layout["new_root"]
    assert current.id == fake_layout["new_key"]
    # 新桶内容逐字节一致
    old_bucket_dir = data_dir / "artifacts" / "records" / fake_layout["old_bucket"] / "2026"
    new_bucket_dir = data_dir / "artifacts" / "records" / fake_layout["new_bucket"] / "2026"
    for name in ("r1.json", "r2.json"):
        assert (old_bucket_dir / name).read_bytes() == (new_bucket_dir / name).read_bytes()
    # 旧桶保留
    assert old_bucket_dir.is_dir()
    # 第二遍：全幂等（改名 already_done / 改写 0 / 复制 0 / 注册 already_current）
    second = _run_migration(fake_layout)
    assert second["rename_sessions_partition"]["action"] == "already_done"
    assert second["rewrite_identity_owners"]["rewritten"] == 0
    assert second["copy_artifact_records"]["copied"] == 0
    assert second["switch_registry"]["action"] == "already_current"
    # 其它分区仍未动
    assert (sessions / "research-other" / "note.txt").read_text(encoding="utf-8") == "untouched"
    # 新根已按 0700 建好
    import stat as stat_mod

    assert stat_mod.S_IMODE(fake_layout["new_root"].stat().st_mode) & 0o777 == 0o700


# rehearse 端到端（tmp 假数据；Phase 0 预检在假 data 上通过）
def test_rehearse_end_to_end_on_fake_data(fake_layout: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    audit_file = fake_layout["tmp_path"] / "audit" / "campaign.json"
    rc = mw.main([
        "rehearse",
        "--data-dir", str(fake_layout["data_dir"]),
        "--old-root", str(fake_layout["old_root"]),
        "--new-root", str(fake_layout["new_root"]),
        "--audit-file", str(audit_file),
        "--web-port", str(free_port),
    ])
    assert rc == 0, "演练必须 PASS"
    # 审计落盘且含六项校验报告
    import json

    records = json.loads(audit_file.read_text(encoding="utf-8"))
    steps = [r["step"] for r in records]
    assert "rehearse.precheck" in steps and "rehearse.report" in steps
    report = next(r for r in records if r["step"] == "rehearse.report")
    assert report["result"] == "PASS"
    assert set(report["report"]["checks"]) == {
        "partition_stats_match", "identity_rewrite", "registry_state",
        "conflict_injection", "idempotent_rerun", "current_points_to_new_root",
    }
    # 真实假数据未被迁移（镜像内完成；源分区原位）
    assert (fake_layout["data_dir"] / "sessions" / fake_layout["old_key"] / "2026").is_dir()


# migrate/rollback 门卫：未 --yes 拒绝；预检失败拒绝
def test_migrate_requires_yes_and_stopped_services(fake_layout: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    common = [
        "--data-dir", str(fake_layout["data_dir"]),
        "--old-root", str(fake_layout["old_root"]),
        "--new-root", str(fake_layout["new_root"]),
        "--web-port", str(free_port),
    ]
    assert mw.main(["migrate", *common]) == 2  # 未 --yes → 拒绝执行
    # 伪造存活 manifest → Phase 0 预检失败（即使 --yes 也不动）
    runtime_dir = fake_layout["data_dir"] / "runtime"
    runtime_dir.mkdir(exist_ok=True)
    (runtime_dir / "runtime_manifest.web.json").write_text(
        '{"pid": 1}', encoding="utf-8"  # pid 1 恒存活
    )
    assert mw.main(["migrate", "--yes", *common]) == 2
    # 数据未被动过
    assert (fake_layout["data_dir"] / "sessions" / fake_layout["old_key"] / "2026").is_dir()
