"""合并队列（P2a·S0）单测: 串行互斥 / stale 重排 / merge-tree 冲突 / 凭证校验 / 建议卡顺序.

全部用 tmp_path 造账本与临时 git 仓库（git init + 若干 commit），不碰真实仓库与 data/。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.introspection.merge_queue import (
    VERIFY_LAYER_DISABLED,
    MergeNotSupportedError,
    MergeQueueConstraintError,
    MergeQueueCorruptionError,
    MergeQueueStore,
    MergeQueueVersionConflictError,
    attempt_auto_merge,
    auto_merge_enabled,
    automation_status,
    build_merge_advice,
    check_verify_covers_base,
    verify_layer_status,
)
from llm_loop.timekeeping import system_local_now


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, f"git {args} 失败: {proc.stderr.strip()}"
    return proc.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "base")
    return root


@pytest.fixture()
def store(tmp_path: Path, repo: Path) -> MergeQueueStore:
    return MergeQueueStore(tmp_path / "audit", repo_root=str(repo))


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "main")


def _branch_commit(repo: Path, branch: str, rel: str, content: str) -> str:
    """从 main 拉分支、提交一个文件、回到 main，返回分支 head sha（不动 main）。"""
    _git(repo, "checkout", "-b", branch, "main")
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-m", f"change {rel}")
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "main")
    return sha


def _advance_main(repo: Path, rel: str, content: str) -> str:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-m", f"main: change {rel}")
    return _head(repo)


def _write_receipt(
    store: MergeQueueStore, receipt_id: str, lane_id: str, base_sha: str, *, result: str = "pass"
) -> None:
    row = {
        "receipt_id": receipt_id,
        "lane_id": lane_id,
        "base_sha": base_sha,
        "result": result,
        "created_at": system_local_now().isoformat(),
        # 有效期必须显式给出：check_verify_covers_base 对缺失 ttl_s 按 fail-closed
        # 处理（不可判定 ≠ 永不过期），所以测试凭证必须携带真实 ttl。
        "ttl_s": 3600,
    }
    path = Path(store.receipts_path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _enqueue(
    store: MergeQueueStore, lane_id: str, *, head: str, base: str, paths: list[str], verify_ref: str
) -> dict:
    return store.enqueue(
        lane_id=lane_id,
        branch=f"fix/{lane_id}",
        head_sha=head,
        base_main_sha=base,
        paths=paths,
        verify_ref=verify_ref,
    )


def test_preflight_serialized_second_rejected(store: MergeQueueStore, repo: Path) -> None:
    head = _head(repo)
    a = _enqueue(store, "lane-a", head=head, base=head, paths=["src/a.py"], verify_ref="vr-a")
    _enqueue(store, "lane-b", head=head, base=head, paths=["src/b.py"], verify_ref="vr-b")

    first = store.request_preflight("lane-a", expected_version=a["version"])
    assert first["ok"] is True
    assert first["entry"]["status"] == "preflight"

    second = store.request_preflight("lane-b", expected_version=1)
    assert second["ok"] is False
    assert second["reason_code"] == "merge_slot_busy"
    assert second["holder"]["lane_id"] == "lane-a"
    # 被拒方保持在 queued，不降级、不删除
    assert store.get("lane-b")["status"] == "queued"
    # slot 持有者跨进程可见（由 state 文件推导，非内存）
    assert store.slot_holder()["lane_id"] == "lane-a"

    # 释放路径: 持有者 abort 后，第二位可进入
    holder = store.get("lane-a")
    store.abort("lane-a", expected_version=holder["version"], reason="人工撤回")
    retry = store.request_preflight("lane-b", expected_version=1)
    assert retry["ok"] is True
    assert store.slot_holder()["lane_id"] == "lane-b"


def test_main_advance_marks_queued_stale_and_keeps(store: MergeQueueStore, repo: Path) -> None:
    h0 = _head(repo)
    lane_head = _branch_commit(repo, "fix/cla", "lane_note.md", "lane change\n")
    _write_receipt(store, "vr-a", "lane-a", h0)
    _enqueue(
        store, "lane-a", head=lane_head, base=h0, paths=["lane_note.md"], verify_ref="vr-a"
    )

    h1 = _advance_main(repo, "main_note.md", "main change\n")
    staled = store.note_main_advanced(h1)
    assert len(staled) == 1

    entry = store.get("lane-a")
    assert entry["status"] == "queued"  # 仍在队列，不删除
    assert entry["stale"] is True
    assert "main_advanced" in entry["stale_reasons"]
    assert entry["stale_since_main"] == h1
    assert entry["version"] == 2
    # 幂等：同 sha 重复通知不重复递增
    assert store.note_main_advanced(h1) == []
    assert store.get("lane-a")["version"] == 2
    # stale 项仍非终态、仍可见，且可再次申请 preflight（不拒绝）
    assert [e["lane_id"] for e in store.list()] == ["lane-a"]
    req = store.request_preflight("lane-a", expected_version=2)
    assert req["ok"] is True

    result = store.run_preflight("lane-a", expected_version=3)
    assert result["verdict"] == "fail"
    assert result["reason_codes"] == ["base_stale"]
    assert result["status"] == "failed"

    # 重新 preflight 可继续: requeue 刷新 base 后回 queued
    again = store.requeue("lane-a", expected_version=4, base_main_sha=h1)
    assert again["status"] == "queued"
    assert again["stale"] is False


def test_merge_tree_conflict_detected(store: MergeQueueStore, repo: Path) -> None:
    lane_head = _branch_commit(repo, "fix/conflict", "README.md", "lane version\n")
    h1 = _advance_main(repo, "README.md", "main version\n")  # 与 lane 改同一行 → 真冲突
    _write_receipt(store, "vr-a", "lane-a", h1)
    _enqueue(
        store, "lane-a", head=lane_head, base=h1, paths=["README.md"], verify_ref="vr-a"
    )

    store.request_preflight("lane-a", expected_version=1)
    result = store.run_preflight("lane-a", expected_version=2)
    assert result["verdict"] == "fail"
    # 只有机检 b 失败（base 已声明为最新、凭证匹配、无其他在途项）
    assert result["reason_codes"] == ["merge_conflict"]
    conflict_check = next(c for c in result["checks"] if c["check"] == "merge_tree_clean")
    assert "README.md" in conflict_check["evidence"]["conflicts"]
    assert store.get("lane-a")["status"] == "failed"


def test_verify_receipt_mismatch_rejected(store: MergeQueueStore, repo: Path) -> None:
    h0 = _head(repo)
    lane_head = _branch_commit(repo, "fix/v", "src/new.py", "print('v')\n")
    h1 = _advance_main(repo, "README.md", "main moved\n")
    _write_receipt(store, "vr-old", "lane-a", h0)  # 凭证 base 是旧 main
    _enqueue(
        store, "lane-a", head=lane_head, base=h1, paths=["src/new.py"], verify_ref="vr-old"
    )

    store.request_preflight("lane-a", expected_version=1)
    result = store.run_preflight("lane-a", expected_version=2)
    assert result["verdict"] == "fail"
    assert result["reason_codes"] == ["verify_stale"]
    assert store.get("lane-a")["status"] == "failed"

    # 无凭证（A10 口径）: verify_ref 为空 → verify_required
    other_head = _branch_commit(repo, "fix/c", "src/c.py", "print('c')\n")
    _enqueue(store, "lane-c", head=other_head, base=h1, paths=["src/c.py"], verify_ref="")
    store.request_preflight("lane-c", expected_version=1)
    result_c = store.run_preflight("lane-c", expected_version=2)
    assert "verify_required" in result_c["reason_codes"]


def test_advice_card_orders_disjoint_first(store: MergeQueueStore, repo: Path) -> None:
    h0 = _head(repo)
    d_head = _branch_commit(repo, "fix/d", "src/only_a.py", "a = 1\n")
    x_head = _branch_commit(repo, "fix/x", "src/x1.py", "x = 1\n")
    y_head = _branch_commit(repo, "fix/y", "src/y1.py", "y = 1\n")
    _write_receipt(store, "vr-d", "lane-d", h0)
    _write_receipt(store, "vr-x", "lane-x", h0)
    _write_receipt(store, "vr-y", "lane-y", h0)
    _enqueue(store, "lane-d", head=d_head, base=h0, paths=["src/only_a.py"], verify_ref="vr-d")
    # x 与 y 声明 paths 相交（实际改动不同文件 → merge-tree 零冲突，纯 paths 交叉）
    _enqueue(store, "lane-x", head=x_head, base=h0, paths=["src/shared.py"], verify_ref="vr-x")
    _enqueue(
        store, "lane-y", head=y_head, base=h0, paths=["src/shared.py", "src/y1.py"], verify_ref="vr-y"
    )

    card = build_merge_advice(store)
    assert card["main_head"] == h0
    orders = {lane["lane_id"]: lane["suggested_order"] for lane in card["lanes"]}
    # 无冲突且 paths 不相交者优先，有交叉者后置
    assert orders["lane-d"] == 1
    assert orders["lane-x"] in (2, 3)
    assert orders["lane-y"] in (2, 3)
    # 卡级 reason_codes 覆盖交叉事实
    assert "lane-x:paths_overlap" in card["reason_codes"]
    assert "lane-y:paths_overlap" in card["reason_codes"]
    lane_d = next(x for x in card["lanes"] if x["lane_id"] == "lane-d")
    assert lane_d["conflicts"] == []
    assert lane_d["needs_reverify"] == []
    assert sorted(lane_d["overlaps_with"]) == []
    # 父代理补充要求: S0 无 merge commit，按 --no-ff 政策预判（不把未知当 false）
    for lane in card["lanes"]:
        assert lane["revertible"] is True
        assert lane["revert_blocker"] == "predicted_from_no_ff_policy"


def test_auto_merge_switch_gates_but_never_executes() -> None:
    assert auto_merge_enabled() is False
    status = automation_status()
    assert status["level"] == "S0"
    assert status["lane_auto_merge"] is False
    assert status["executor"] == "not_implemented"
    with pytest.raises(MergeNotSupportedError, match="P2b"):
        attempt_auto_merge()

    # 开关只能由配置层注入（本模块不读环境）；S0 阶段即使为 true 也绝不执行 merge/push
    on = SimpleNamespace(auto_merge=True)
    assert auto_merge_enabled(on) is True
    assert automation_status(on)["lane_auto_merge"] is True
    with pytest.raises(MergeNotSupportedError, match="S0 阶段不执行"):
        attempt_auto_merge(on)


def test_version_cas_conflict(store: MergeQueueStore, repo: Path) -> None:
    head = _head(repo)
    _enqueue(store, "lane-a", head=head, base=head, paths=["src/a.py"], verify_ref="")
    with pytest.raises(MergeQueueVersionConflictError) as exc:
        store.request_preflight("lane-a", expected_version=7)
    assert exc.value.current == 1
    assert store.get("lane-a")["status"] == "queued"  # 冲突不写入


def test_corrupt_state_fails_closed(store: MergeQueueStore, repo: Path) -> None:
    head = _head(repo)
    _enqueue(store, "lane-a", head=head, base=head, paths=["src/a.py"], verify_ref="")
    with (Path(store.receipts_path).parent / "merge_queue.jsonl").open(
        "a", encoding="utf-8"
    ) as fh:
        fh.write("{not json\n")
    with pytest.raises(MergeQueueCorruptionError):
        store.list()
    with pytest.raises(MergeQueueCorruptionError):
        _enqueue(store, "lane-b", head=head, base=head, paths=["src/b.py"], verify_ref="")


def test_events_audit_trail(store: MergeQueueStore, repo: Path) -> None:
    head = _head(repo)
    _enqueue(store, "lane-a", head=head, base=head, paths=["src/a.py"], verify_ref="")
    store.request_preflight("lane-a", expected_version=1)
    events_path = Path(store.receipts_path).parent / "merge_queue_events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [e["event"] for e in events] == ["queue.enqueued", "queue.preflight_started"]
    assert events[0]["lane_id"] == "lane-a"
    assert events[1]["version"] == 2


def test_enqueue_requires_lane_snapshot_fields(store: MergeQueueStore) -> None:
    with pytest.raises(MergeQueueConstraintError, match="head_sha 必填"):
        store.enqueue(lane_id="lane-x", branch="fix/x", head_sha="", base_main_sha="a" * 40)
    with pytest.raises(MergeQueueConstraintError, match="base_main_sha 必填"):
        store.enqueue(lane_id="lane-x", branch="fix/x", head_sha="b" * 40, base_main_sha="")


def test_preflight_pass_releases_slot_for_next_lane(
    store: MergeQueueStore, repo: Path
) -> None:
    """S0 关键行为：机检全过必须交还 slot。

    反例即原缺陷：全过项继续持 slot，人不在场时后续 lane 永远进不了机检，
    整个队列被一个「等人确认」的项卡死。
    """
    h0 = _head(repo)
    lane_head = _branch_commit(repo, "fix/oka", "ok_a.md", "a\n")
    _write_receipt(store, "vr-oka", "lane-a", h0)
    a = _enqueue(
        store, "lane-a", head=lane_head, base=h0, paths=["ok_a.md"], verify_ref="vr-oka"
    )
    b = _enqueue(store, "lane-b", head=h0, base=h0, paths=["ok_b.md"], verify_ref="vr-okb")

    started = store.request_preflight("lane-a", expected_version=a["version"])
    assert started["ok"] is True, started
    first = store.run_preflight(
        "lane-a", expected_version=started["entry"]["version"]
    )
    assert first["verdict"] == "pass", first
    assert first["status"] == "ready_for_confirm"
    passed_row = store.get("lane-a")
    assert passed_row["slot_acquired_at"] == ""
    assert store.slot_holder() is None

    # 后续 lane 立刻可进机检，无需先 abort 掉前一个全过项
    second = store.request_preflight("lane-b", expected_version=b["version"])
    assert second["ok"] is True
    assert store.slot_holder()["lane_id"] == "lane-b"


def test_request_merge_and_mark_merged_cycle(
    store: MergeQueueStore, repo: Path
) -> None:
    h0 = _head(repo)
    lane_head = _branch_commit(repo, "fix/cyc", "cyc.md", "c\n")
    _write_receipt(store, "vr-cyc", "lane-c", h0)
    entry = _enqueue(
        store, "lane-c", head=lane_head, base=h0, paths=["cyc.md"], verify_ref="vr-cyc"
    )
    started = store.request_preflight("lane-c", expected_version=entry["version"])
    assert started["ok"] is True, started
    passed = store.run_preflight(
        "lane-c", expected_version=started["entry"]["version"]
    )
    assert passed["verdict"] == "pass", passed

    ready = store.get("lane-c")
    confirmed = store.request_merge(
        "lane-c", expected_version=ready["version"], slot_owner="sess-1"
    )
    assert confirmed["ok"] is True
    assert confirmed["entry"]["status"] == "merging"
    assert store.slot_holder()["lane_id"] == "lane-c"

    merged = store.mark_merged(
        "lane-c",
        expected_version=confirmed["entry"]["version"],
        merge_commit="deadbeef",
    )
    assert merged["status"] == "merged"
    assert merged["merge_commit"] == "deadbeef"
    assert store.slot_holder() is None


def test_request_merge_rejected_when_not_ready(
    store: MergeQueueStore, repo: Path
) -> None:
    h0 = _head(repo)
    entry = _enqueue(store, "lane-d", head=h0, base=h0, paths=["d.md"], verify_ref="vr-d")
    res = store.request_merge("lane-d", expected_version=entry["version"])
    assert res["ok"] is False
    assert res["reason_code"] == "not_ready_for_confirm"



# ── EVO-20261105-501db776: verify 凭证层「未启用」与「凭证缺失」必须可区分 ──
# 事实：生产代码只读 verify_receipts.jsonl，无任何签发者（唯一写入是测试 helper）。
# 若把「层没启用」报成 verify_required，调用方会以为补一张凭证就能过，
# 实际重试/重验/重新登记都不会改变结果。


def test_verify_layer_status_reports_disabled_when_file_absent(tmp_path: Path) -> None:
    layer = verify_layer_status(tmp_path / "verify_receipts.jsonl")
    assert layer["enabled"] is False
    assert layer["file_exists"] is False
    assert layer["receipt_count"] == 0
    assert "未启用" in layer["detail"]


def test_verify_layer_status_enabled_when_receipt_present(tmp_path: Path) -> None:
    p = tmp_path / "verify_receipts.jsonl"
    p.write_text(json.dumps({"receipt_id": "vr-1", "result": "pass"}) + "\n", encoding="utf-8")
    layer = verify_layer_status(p)
    assert layer["enabled"] is True
    assert layer["receipt_count"] == 1
    assert "detail" not in layer


def test_verify_disabled_layer_reports_layer_code_not_verify_required() -> None:
    entry = {"lane_id": "lane-x", "base_main_sha": "a" * 40}
    layer = {"enabled": False, "detail": "verify 层当前未启用"}
    # 有 verify_ref 但层是空的
    res = check_verify_covers_base({**entry, "verify_ref": "vr-x"}, {}, layer=layer)
    assert res["verdict"] == "fail"
    assert res["reason_code"] == VERIFY_LAYER_DISABLED
    # 连 verify_ref 都没有：同样指向层未启用，而不是催人补凭证
    res2 = check_verify_covers_base(entry, {}, layer=layer)
    assert res2["reason_code"] == VERIFY_LAYER_DISABLED


def test_verify_enabled_layer_keeps_original_semantics(tmp_path: Path) -> None:
    """层启用了（有别的凭证）但这条 ref 不存在 → 仍是 verify_required（旧语义不退化）."""
    p = tmp_path / "verify_receipts.jsonl"
    p.write_text(json.dumps({"receipt_id": "vr-other", "result": "pass"}) + "\n", encoding="utf-8")
    layer = verify_layer_status(p)
    assert layer["enabled"] is True
    entry = {"lane_id": "lane-x", "base_main_sha": "a" * 40, "verify_ref": "vr-missing"}
    res = check_verify_covers_base(entry, {"vr-other": {"receipt_id": "vr-other"}}, layer=layer)
    assert res["reason_code"] == "verify_required"
