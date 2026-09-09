"""单元测试: 任务级 Goal 状态机 + checkpoint 四要素（EVO-20260824-3cd4d74b）.

覆盖:
1. create → checkpoint（四要素）→ get（恢复视图）→ complete 生命周期
2. blocked 仅严格条件（状态机限制）
3. 非 active 目标 checkpoint 拒绝（如实不写入）
4. 多 checkpoint 累积 + 最近优先
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.introspection.goal import GOAL_STATUSES, GoalStore


def _store(tmp_path: Path) -> GoalStore:
    return GoalStore(str(tmp_path))


def test_lifecycle_create_checkpoint_complete(tmp_path):
    s = _store(tmp_path)
    g = s.create("深度审计项目", session_id="s1")
    assert g.status == "active"
    assert g.id.startswith("GOAL-")

    # checkpoint 四要素
    upd = s.checkpoint(
        g.id,
        what="完成审计框架",
        evidence="architecture_status success",
        path="src/llm_loop/",
        next_step="分析缓存命中",
    )
    assert upd is not None
    assert len(upd["checkpoints"]) == 1
    cp = upd["checkpoints"][0]
    assert cp["what"] == "完成审计框架"
    assert cp["evidence"] == "architecture_status success"
    assert cp["path"] == "src/llm_loop/"
    assert cp["next"] == "分析缓存命中"

    # get 恢复视图
    got = s.get(g.id)
    assert got["id"] == g.id
    assert got["status"] == "active"
    assert len(got["checkpoints"]) == 1

    # complete（证据驱动）
    done = s.update(g.id, "complete", reason="全部需求已用工具回执验证")
    assert done["status"] == "complete"
    assert done["completed_at"]


def test_checkpoint_rejected_when_not_active(tmp_path):
    s = _store(tmp_path)
    g = s.create("任务", session_id="s1")
    s.update(g.id, "complete")
    # 非 active 目标 checkpoint → 明确拒绝，不得让工具层误报“已记录”。
    upd = s.checkpoint(g.id, what="不应写入")
    assert upd is None
    assert len(s.get(g.id).get("checkpoints", [])) == 0


def test_update_blocked_requires_reason_path(tmp_path):
    s = _store(tmp_path)
    g = s.create("任务", session_id="s1")
    b = s.update(g.id, "blocked", reason="外部依赖未就绪")
    assert b["status"] == "blocked"
    assert b["blocked_reason"] == "外部依赖未就绪"


def test_invalid_status_rejected(tmp_path):
    s = _store(tmp_path)
    g = s.create("任务", session_id="s1")
    try:
        s.update(g.id, "done")
        raise AssertionError("应拒绝非法状态")
    except ValueError:
        pass


def test_get_returns_latest_active_or_last(tmp_path):
    s = _store(tmp_path)
    g1 = s.create("目标1", session_id="s1")
    s.update(g1.id, "complete")
    g2 = s.create("目标2", session_id="s1")
    got = s.get()  # 无 id: 最近 active（目标2）
    assert got["id"] == g2.id
    # 全部 complete 后 → 取最近一条
    s.update(g2.id, "complete")
    got2 = s.get()
    assert got2["id"] == g2.id


def test_multiple_checkpoints_recent_first(tmp_path):
    s = _store(tmp_path)
    g = s.create("任务", session_id="s1")
    for i in range(5):
        s.checkpoint(g.id, what=f"里程碑{i}", evidence="ev", path="p", next_step="n")
    got = s.get(g.id)
    assert len(got["checkpoints"]) == 5
    assert got["checkpoints"][-1]["what"] == "里程碑4"


def test_goal_statuses_constant():
    assert set(GOAL_STATUSES) == {"active", "complete", "blocked"}


def test_checkpoint_tool_reports_terminal_goal_as_failure(tmp_path):
    """complete/blocked Goal 上 checkpoint 必须是失败回执，不能误报“已记录”。"""
    from llm_loop.introspection.tools_goal import run_checkpoint_goal

    store = _store(tmp_path)
    goal = store.create("终态checkpoint测试", session_id="s1")
    store.update(goal.id, "complete")
    host = SimpleNamespace(audit_dir=tmp_path)
    ctx = SimpleNamespace(session_id="s1")

    result = run_checkpoint_goal(ctx, host, {"goal_id": goal.id, "what": "不应写入"})

    assert result.status.value == "failure"
    assert "不存在或非 active" in result.content


def test_goal_terminal_state_cannot_transition_to_other_terminal(tmp_path):
    """状态机只能 active→complete/blocked；terminal 不得二次改写成另一terminal。"""
    s = _store(tmp_path)
    goal = s.create("终态不可逆", session_id="s1")
    s.update(goal.id, "complete")

    try:
        s.update(goal.id, "blocked", reason="不应覆盖完成态")
        raise AssertionError("complete → blocked 应被拒绝")
    except ValueError:
        pass
    assert s.get(goal.id)["status"] == "complete"


def test_goal_blocked_requires_nonempty_reason(tmp_path):
    """blocked 至少必须显式记录严格阻塞原因，不能产生不可解释终态。"""
    s = _store(tmp_path)
    goal = s.create("阻塞理由", session_id="s1")
    try:
        s.update(goal.id, "blocked", reason="")
        raise AssertionError("blocked 缺 reason 应被拒绝")
    except ValueError:
        pass
    assert s.get(goal.id)["status"] == "active"


def test_create_cannot_be_lost_during_concurrent_checkpoint(tmp_path, monkeypatch):
    """create 与checkpoint必须共享同一跨进程写锁；否则checkpoint重写会吞并发新Goal。"""
    store = _store(tmp_path)
    first = store.create("first", session_id="s1")
    checkpoint_read = threading.Event()
    release_checkpoint = threading.Event()
    create_done = threading.Event()
    errors: list[BaseException] = []
    created: list[str] = []
    original_read_text = Path.read_text

    def blocked_read_text(path: Path, *args, **kwargs):
        data = original_read_text(path, *args, **kwargs)
        if path == store._path and threading.current_thread().name == "goal-checkpoint":  # noqa: SLF001
            checkpoint_read.set()
            if not release_checkpoint.wait(5):
                raise TimeoutError("checkpoint test barrier timeout")
        return data

    monkeypatch.setattr(Path, "read_text", blocked_read_text)

    def do_checkpoint():
        try:
            store.checkpoint(first.id, what="checkpoint")
        except BaseException as exc:  # noqa: BLE001 — 测试线程错误回传
            errors.append(exc)

    def do_create():
        try:
            created.append(store.create("second", session_id="s2").id)
        except BaseException as exc:  # noqa: BLE001 — 测试线程错误回传
            errors.append(exc)
        finally:
            create_done.set()

    t_cp = threading.Thread(target=do_checkpoint, name="goal-checkpoint")
    t_cp.start()
    assert checkpoint_read.wait(5)
    t_create = threading.Thread(target=do_create, name="goal-create")
    t_create.start()
    # 旧实现create无锁，会在checkpoint释放前完成；修复后会等待同一写锁。
    create_done.wait(0.2)
    release_checkpoint.set()
    t_cp.join(5)
    t_create.join(5)

    assert not errors
    assert created
    created_goal = store.get(created[0])
    assert created_goal is not None and created_goal["id"] == created[0], (
        "并发create不得被checkpoint全量重写吞掉"
    )
    assert store.get(first.id)["checkpoints"][-1]["what"] == "checkpoint"


def test_get_explicit_unknown_goal_id_returns_none(tmp_path):
    """显式goal_id未命中时必须返回None，不能静默回退其他active/latest目标。"""
    s = _store(tmp_path)
    existing = s.create("existing", session_id="s1")
    assert s.get(existing.id)["id"] == existing.id
    assert s.get("GOAL-20990101-doesnotexist") is None


def test_get_goal_tool_unknown_id_does_not_leak_other_goal(tmp_path):
    """工具层显式错误goal_id不能返回另一个目标的objective/checkpoint上下文。"""
    from llm_loop.introspection.tools_goal import run_get_goal

    store = _store(tmp_path)
    existing = store.create("SECRET-OTHER-GOAL", session_id="s1")
    host = SimpleNamespace(audit_dir=tmp_path)
    ctx = SimpleNamespace(session_id="s1")

    result = run_get_goal(ctx, host, {"goal_id": "GOAL-20990101-doesnotexist"})

    assert existing.objective not in result.content
    assert "不存在" in result.content or "无活动目标" in result.content


def test_goal_atomic_rewrite_reader_sees_complete_old_then_new(tmp_path, monkeypatch):
    """writer在os.replace前停住时，锁外reader应仍读到完整旧快照；提交后读完整新快照。"""
    import llm_loop.introspection.goal as goal_mod

    store = _store(tmp_path)
    goal = store.create("atomic-reader", session_id="s1")
    replace_ready = threading.Event()
    release_replace = threading.Event()
    errors: list[BaseException] = []
    original_replace = goal_mod.os.replace

    def blocked_replace(src, dst):
        if Path(dst) == store._path and threading.current_thread().name == "goal-writer":  # noqa: SLF001
            replace_ready.set()
            if not release_replace.wait(5):
                raise TimeoutError("replace barrier timeout")
        return original_replace(src, dst)

    monkeypatch.setattr(goal_mod.os, "replace", blocked_replace)

    def writer():
        try:
            store.checkpoint(goal.id, what="atomic checkpoint")
        except BaseException as exc:  # noqa: BLE001 — 测试线程错误回传
            errors.append(exc)

    thread = threading.Thread(target=writer, name="goal-writer")
    thread.start()
    assert replace_ready.wait(5)
    mid = store.get(goal.id)
    assert mid is not None and mid["id"] == goal.id
    assert mid.get("checkpoints", []) == [], "replace前reader必须看到完整旧快照"
    release_replace.set()
    thread.join(5)

    assert not errors
    after = store.get(goal.id)
    assert after is not None and after["checkpoints"][-1]["what"] == "atomic checkpoint"


def test_goal_file_lock_does_not_swallow_body_oserror(tmp_path, monkeypatch):
    """写入I/O错误必须原样抛出，不能被_file_lock误判为锁故障后二次yield。"""
    store = _store(tmp_path)

    def fail_write(_lines):
        raise OSError("disk-full-sentinel")

    monkeypatch.setattr(store, "_atomic_rewrite", fail_write)
    try:
        store.create("io-error", session_id="s1")
        raise AssertionError("应传播业务写入OSError")
    except OSError as exc:
        assert "disk-full-sentinel" in str(exc)


def test_create_goal_uses_current_run_session_id(tmp_path):
    """未显式传session_id时，create_goal必须归属当前ContextVar session而非共享ctx最后写入者。"""
    from llm_loop.core.run_context import current_session_id
    from llm_loop.introspection.tools_goal import run_create_goal

    host = SimpleNamespace(audit_dir=tmp_path)
    ctx = SimpleNamespace(session_id="session-B")
    token = current_session_id.set("session-A")
    try:
        result = run_create_goal(ctx, host, {"objective": "goal session attribution"})
    finally:
        current_session_id.reset(token)

    assert result.status.value == "success"
    stored = _store(tmp_path).get()
    assert stored is not None and stored["session_id"] == "session-A"


def test_get_goal_prefers_current_session_active_before_global_latest(tmp_path):
    """多个会话各有active Goal时，无参数get_goal应优先当前session；无本地Goal时才跨会话回退。"""
    from llm_loop.core.run_context import current_session_id
    from llm_loop.introspection.tools_goal import run_get_goal

    store = _store(tmp_path)
    goal_a = store.create("GOAL-A-CURRENT", session_id="session-A")
    goal_b = store.create("GOAL-B-LATEST", session_id="session-B")
    assert store.get()["id"] == goal_b.id  # 存储层旧全局语义保留

    host = SimpleNamespace(audit_dir=tmp_path)
    ctx = SimpleNamespace(session_id="session-B")  # 模拟共享ctx最后写入者
    token = current_session_id.set("session-A")
    try:
        result = run_get_goal(ctx, host, {})
    finally:
        current_session_id.reset(token)

    assert result.status.value == "success"
    assert goal_a.objective in result.content
    assert goal_b.objective not in result.content


def test_get_goal_without_local_active_keeps_cross_session_fallback(tmp_path):
    """当前session无active Goal时仍可回退全局active，保留跨会话续做能力。"""
    from llm_loop.core.run_context import current_session_id
    from llm_loop.introspection.tools_goal import run_get_goal

    store = _store(tmp_path)
    global_goal = store.create("GLOBAL-CROSS-SESSION", session_id="session-B")
    host = SimpleNamespace(audit_dir=tmp_path)
    ctx = SimpleNamespace(session_id="session-C")
    token = current_session_id.set("session-A")
    try:
        result = run_get_goal(ctx, host, {})
    finally:
        current_session_id.reset(token)

    assert result.status.value == "success"
    assert global_goal.objective in result.content


def test_goal_cross_process_create_and_checkpoint_are_lossless(tmp_path):
    """真实多进程同时create+checkpoint不得lost-update或留下损坏JSON。"""
    store = _store(tmp_path)
    shared = store.create("shared-cross-process", session_id="root")
    start_at = time.time() + 0.6
    code = (
        "import sys,time\n"
        "from llm_loop.introspection.goal import GoalStore\n"
        "audit_dir,shared_id,worker,start_at=sys.argv[1],sys.argv[2],sys.argv[3],float(sys.argv[4])\n"
        "while time.time()<start_at: time.sleep(0.005)\n"
        "store=GoalStore(audit_dir)\n"
        "g=store.create(f'worker-{worker}', session_id=worker)\n"
        "store.checkpoint(g.id, what=f'own-{worker}')\n"
        "store.checkpoint(shared_id, what=f'shared-{worker}')\n"
    )
    env = os.environ.copy()
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(tmp_path), shared.id, str(i), str(start_at)],
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for i in range(6)
    ]
    failures = []
    for proc in procs:
        out, err = proc.communicate(timeout=20)
        if proc.returncode != 0:
            failures.append((proc.returncode, out, err))
    assert not failures

    rows = store.list(limit=100)
    by_objective = {row["objective"]: row for row in rows}
    assert "shared-cross-process" in by_objective
    for i in range(6):
        row = by_objective[f"worker-{i}"]
        assert row["checkpoints"][-1]["what"] == f"own-{i}"
    shared_row = store.get(shared.id)
    assert shared_row is not None
    shared_whats = {cp["what"] for cp in shared_row["checkpoints"]}
    assert shared_whats == {f"shared-{i}" for i in range(6)}

    import json

    raw_lines = (tmp_path / "goals.jsonl").read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in raw_lines if line.strip()]
    assert len(parsed) == 7


def test_goal_implicit_get_refuses_newer_corrupt_record(tmp_path):
    """自动恢复不能在候选Goal之后存在损坏记录时静默回退旧Goal；显式已知有效id仍可读。"""
    store = _store(tmp_path)
    valid = store.create("older-valid", session_id="session-A")
    path = tmp_path / "goals.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write('{"id":"GOAL-BROKEN","objective":"newer-active","status":"active"\n')

    assert store.get(valid.id)["id"] == valid.id
    with pytest.raises(RuntimeError, match="存储损坏"):
        store.get()
    with pytest.raises(RuntimeError, match="存储损坏"):
        store.get("GOAL-BROKEN")


def test_run_get_goal_reports_corruption_instead_of_resuming_old_goal(tmp_path):
    """工具层遇损坏GoalStore必须fail-closed，不得把较旧Goal伪装成当前恢复目标。"""
    from llm_loop.introspection.tools_goal import run_get_goal

    store = _store(tmp_path)
    older = store.create("OLDER-MUST-NOT-RESUME", session_id="session-A")
    path = tmp_path / "goals.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write('{"id":"GOAL-BROKEN","objective":"newer-active","status":"active"\n')

    host = SimpleNamespace(audit_dir=tmp_path)
    ctx = SimpleNamespace(session_id="session-A")
    result = run_get_goal(ctx, host, {})

    assert result.status.value == "failure"
    assert "存储损坏" in result.content
    assert older.objective not in result.content


def test_goal_implicit_get_allows_new_valid_after_older_corrupt_record(tmp_path, caplog):
    """坏行仅位于更旧位置时，后来创建的有效Goal足以恢复；不因历史损坏永久阻塞。"""
    path = tmp_path / "goals.jsonl"
    path.write_text('{"id":"OLD-BROKEN","status":"active"\n', encoding="utf-8")
    store = _store(tmp_path)
    newer = store.create("newer-valid", session_id="session-A")

    with caplog.at_level("WARNING", logger="llm_loop.introspection.goal"):
        got = store.get(prefer_session_id="session-A")

    assert got is not None and got["id"] == newer.id
    assert any("较旧损坏行" in record.message for record in caplog.records)


# ── CR-R1.1: strict_session 严格会话读（审查项2：跨会话 Goal 污染回归）──


def test_get_strict_session_no_cross_session_fallback(tmp_path):
    """CR-R1.1 回归：strict 读禁止跨会话回退——A 看不到 B 的 active goal.

    审查实测：A 无候选 + B active 时旧版 get(prefer_session_id=A) 返回 B 的
    active goal（全局回退链），且 B 的 objective 随后写入 A 的语义分片。
    """
    store = _store(tmp_path)
    gb = store.create("B 活跃目标", session_id="session-B")

    # strict：A 会话读不到 B 的 active（宁缺勿错，不变量①）
    got = store.get(prefer_session_id="session-A", strict_session=True)
    assert got is None
    # 默认（恢复性读取）保持全局回退语义不变——B 的 active 可见
    relaxed = store.get(prefer_session_id="session-A")
    assert relaxed is not None and relaxed["id"] == gb.id
    # strict 下本会话 active 可见
    own = store.get(prefer_session_id="session-B", strict_session=True)
    assert own is not None and own["id"] == gb.id


def test_get_strict_session_prefers_own_latest_over_foreign_active(tmp_path):
    """CR-R1.1: strict 下 preferred latest（本会话终态）优先于全局 active."""
    store = _store(tmp_path)
    ga = store.create("A 已完成目标", session_id="session-A")
    store.update(ga.id, "complete")
    store.create("B 活跃目标", session_id="session-B")

    got = store.get(prefer_session_id="session-A", strict_session=True)
    # 返回的是 A 自己的（终态）而非 B 的 active；rebuild_state 对终态返回
    # None → header 不注入（宁缺勿错），不会把 B 的目标投影进 A 的 prompt。
    assert got is not None and got["id"] == ga.id


def test_checkpoint_goal_reports_corruption_when_target_may_be_malformed(tmp_path):
    """checkpoint目标未命中但文件有坏行时，不能误报不存在/非active。"""
    from llm_loop.introspection.tools_goal import run_checkpoint_goal

    path = tmp_path / "goals.jsonl"
    path.write_text('{"id":"GOAL-BROKEN","status":"active"\n', encoding="utf-8")
    host = SimpleNamespace(audit_dir=tmp_path)
    ctx = SimpleNamespace(session_id="session-A")

    result = run_checkpoint_goal(
        ctx,
        host,
        {"goal_id": "GOAL-BROKEN", "what": "must-not-guess"},
    )

    assert result.status.value == "failure"
    assert "存储损坏" in result.content
    assert "不存在" not in result.content


def test_update_goal_reports_corruption_when_target_may_be_malformed(tmp_path):
    """update目标未命中但文件有坏行时，不能误报不存在。"""
    from llm_loop.introspection.tools_goal import run_update_goal

    path = tmp_path / "goals.jsonl"
    path.write_text('{"id":"GOAL-BROKEN","status":"active"\n', encoding="utf-8")
    host = SimpleNamespace(audit_dir=tmp_path)
    ctx = SimpleNamespace(session_id="session-A")

    result = run_update_goal(
        ctx,
        host,
        {"goal_id": "GOAL-BROKEN", "status": "complete"},
    )

    assert result.status.value == "failure"
    assert "存储损坏" in result.content
    assert "不存在" not in result.content


def test_valid_goal_writes_preserve_unrelated_corrupt_record(tmp_path):
    """显式可解析目标仍可checkpoint/update；无关坏行必须原样保留，不能因修复丢数据。"""
    store = _store(tmp_path)
    valid = store.create("valid-amid-corruption", session_id="session-A")
    path = tmp_path / "goals.jsonl"
    broken = '{"id":"OTHER-BROKEN","status":"active"'
    with path.open("a", encoding="utf-8") as f:
        f.write(broken + "\n")

    checkpointed = store.checkpoint(valid.id, what="safe-write")
    assert checkpointed is not None
    assert checkpointed["checkpoints"][-1]["what"] == "safe-write"
    assert broken in path.read_text(encoding="utf-8").splitlines()

    updated = store.update(valid.id, "complete")
    assert updated is not None and updated["status"] == "complete"
    assert broken in path.read_text(encoding="utf-8").splitlines()


def test_checkpoint_unknown_goal_on_empty_store_returns_none(tmp_path):
    """空GoalStore上的未知checkpoint应正常返回None，不应FileNotFoundError。"""
    store = _store(tmp_path)
    assert store.checkpoint("GOAL-NOT-THERE", what="noop") is None


def test_goal_atomic_rewrite_fsyncs_parent_directory(tmp_path, monkeypatch):
    """os.replace后必须fsync父目录，保证掉电恢复时rename目录项也持久化。"""
    import llm_loop.introspection.goal as goal_mod

    real_open = goal_mod.os.open
    real_fsync = goal_mod.os.fsync
    dir_fds: list[int] = []
    fsynced: list[int] = []

    def track_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        if Path(path) == tmp_path:
            dir_fds.append(fd)
        return fd

    def track_fsync(fd):
        fsynced.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(goal_mod.os, "open", track_open)
    monkeypatch.setattr(goal_mod.os, "fsync", track_fsync)
    _store(tmp_path).create("durable-rename", session_id="s1")

    assert dir_fds, "atomic replace后应显式打开父目录进行fsync"
    assert any(fd in fsynced for fd in dir_fds), "父目录fd必须fsync"
