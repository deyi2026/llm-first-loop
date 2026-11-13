"""M2-2: feishu stale-processing heartbeat 假忙解除（测试矩阵 A-J）.

生产反例（pre-v0.6.51-gen13 备份复原，不含消息正文）：桥 crash 后心跳冻结在
processing 态（pid 已死 / queue0 / last_message_ts 停更 / history 连续同值），
同 msg_id 的 crash 补偿已落盘——旧行为 _target_idle_state 永远 confirmed_busy，
waiting_for_idle 假忙死锁。矩阵 A-J 对应任务书安全边界；证据不足一律
confirmed_busy（_wait_for 把 unconfirmable 当非忙碌推进，禁止绕过门禁）。
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from llm_loop.runtime.service_control import _target_idle_state

MSG_ID = "om_stale_matrix"
STALE_S = 120.0  # 心跳已停更 120s（≥2 个 watchdog 周期 60s）


@pytest.fixture(autouse=True)
def _isolate_compensation_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEISHU_COMPENSATION_PATH", raising=False)
    monkeypatch.delenv("FEISHU_INTERRUPTED_PATH", raising=False)


def _dead_pid() -> int:
    """产出一个确定已死（os.kill → ProcessLookupError）的 pid，最多重试 5 次."""
    for _ in range(5):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        try:
            os.kill(proc.pid, 0)
        except ProcessLookupError:
            return proc.pid
    pytest.fail("无法获得确定已死亡的 pid")


def _iso_local(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


def _write_stale_world(
    root: Path,
    *,
    pid: int | str | None,
    hb_overrides: dict | None = None,
    comp_overrides: dict | None = None,
    comp_lines: list[str] | None = None,
    history_rows: int = 3,
    history_overrides: list[dict] | None = None,
    omit_compensation: bool = False,
    omit_history: bool = False,
) -> dict:
    """构造与生产反例同构的世界：stale 心跳 + history 连续快照 + crash 补偿."""
    now = time.time()
    hb_ts = now - STALE_S
    processing_since = hb_ts - 300.0
    heartbeat = {
        "ts": hb_ts,
        "pid": pid,
        "state": "connected",
        "queue_depth": 0,
        "processing_msg_id": MSG_ID,
        "processing_since": processing_since,
        "last_message_ts": processing_since + 0.001,
        "last_processed_ts": processing_since - 60.0,
        "process_timeout_count": 1,
        "msg_timeout_s": 900.0,
        "silent_suspected": False,
        "silent_since": processing_since + 0.001,
        "reconnect_count": 0,
        "ping_timeout_count": 0,
        "disconnect_count": 0,
    }
    heartbeat.update(hb_overrides or {})
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "feishu_heartbeat.json").write_text(json.dumps(heartbeat), encoding="utf-8")
    if not omit_history:
        overrides = history_overrides or []
        rows = []
        for i in range(history_rows):
            row = dict(heartbeat)
            row["ts"] = hb_ts - 30.0 * (history_rows - 1 - i)
            if i < len(overrides):
                row.update(overrides[i])
            rows.append(row)
        (data / "feishu_heartbeat_history.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
    if not omit_compensation:
        record = {
            "receive_id": "oc_matrix",
            "reply_type": "chat_id",
            "interrupt_cause": "crash",
            "interrupted_at": _iso_local(hb_ts + 19.0),
            "context_ref": "",
            "msg_id": MSG_ID,
        }
        record.update(comp_overrides or {})
        lines = comp_lines if comp_lines is not None else [json.dumps(record)]
        (data / "feishu_compensation.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return heartbeat


def _state(root: Path, target: str = "feishu") -> tuple[str, str]:
    return _target_idle_state(target=target, runtime_root=str(root))


def _write_idle_wecom_heartbeat(root: Path) -> None:
    (root / "data" / "wecom_heartbeat.json").write_text(
        json.dumps({"processing_msg_id": "", "queue_depth": 0}), encoding="utf-8"
    )


# --- 矩阵 A：证据链完整 → confirmed_idle --------------------------------------


def test_matrix_a_full_evidence_confirms_idle(tmp_path: Path) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid())
    assert _state(tmp_path) == ("confirmed_idle", "confirmed_idle")
    # target=all：其余目标空闲（wecom 心跳空闲、无 web 锁、无 learning 在飞）时整体 idle
    _write_idle_wecom_heartbeat(tmp_path)
    assert _state(tmp_path, target="all") == ("confirmed_idle", "confirmed_idle")


def test_matrix_a_compensation_env_relative_resolved_against_runtime_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid())
    data = tmp_path / "data"
    (data / "feishu_compensation.jsonl").rename(data / "custom_comp.jsonl")
    monkeypatch.setenv("FEISHU_COMPENSATION_PATH", "data/custom_comp.jsonl")
    assert _state(tmp_path) == ("confirmed_idle", "confirmed_idle")


# --- 矩阵 B：存活 PID（含真实存活）→ confirmed_busy ----------------------------


def test_matrix_b_live_pid_stays_busy(tmp_path: Path) -> None:
    _write_stale_world(tmp_path, pid=os.getpid())
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "pid_alive_or_unknown" in detail


# --- 矩阵 C：无补偿 → confirmed_busy（不得 unconfirmable 绕过）-----------------


def test_matrix_c_no_compensation_stays_busy_not_unconfirmable(tmp_path: Path) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid(), omit_compensation=True)
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"  # 明确忙碌而非"无法确认"
    assert "compensation_missing" in detail


# --- 矩阵 D：补偿不可读/损坏/时点非法 → confirmed_busy -------------------------


@pytest.mark.parametrize(
    "mode",
    ["corrupt_json", "empty_ts", "unparseable_ts", "early_ts", "other_msg_id"],
)
def test_matrix_d_bad_compensation_stays_busy(tmp_path: Path, mode: str) -> None:
    pid = _dead_pid()
    if mode == "corrupt_json":
        _write_stale_world(tmp_path, pid=pid, comp_lines=['{"receive_id": "oc_matrix"'])
    elif mode == "empty_ts":
        _write_stale_world(tmp_path, pid=pid, comp_overrides={"interrupted_at": ""})
    elif mode == "unparseable_ts":
        _write_stale_world(tmp_path, pid=pid, comp_overrides={"interrupted_at": "not-a-time"})
    elif mode == "other_msg_id":
        _write_stale_world(tmp_path, pid=pid, comp_overrides={"msg_id": "om_other"})
    else:  # early_ts：interrupted_at 早于 processing_since
        heartbeat = _write_stale_world(tmp_path, pid=pid)
        (tmp_path / "data" / "feishu_compensation.jsonl").write_text(
            json.dumps(
                {
                    "receive_id": "oc_matrix",
                    "reply_type": "chat_id",
                    "interrupt_cause": "crash",
                    "interrupted_at": _iso_local(float(heartbeat["processing_since"]) - 400.0),
                    "msg_id": MSG_ID,
                }
            )
            + "\n",
            encoding="utf-8",
        )
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    expected = {
        "corrupt_json": "compensation_unreadable",
        "empty_ts": "compensation_unreadable",
        "unparseable_ts": "compensation_time_invalid",
        "early_ts": "compensation_time_invalid",
        "other_msg_id": "compensation_missing",
    }[mode]
    assert expected in detail


# --- 矩阵 E：queue_depth>0 → confirmed_busy -----------------------------------


def test_matrix_e_queue_depth_positive_stays_busy(tmp_path: Path) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid(), hb_overrides={"queue_depth": 2})
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "queue_depth=2" in detail
    assert "stale-processing" not in detail  # queue>0 不进证据链


# --- 矩阵 F：后续入队迹象 → confirmed_busy ------------------------------------


def test_matrix_f_subsequent_message_stays_busy(tmp_path: Path) -> None:
    # last_message_ts 晚于 processing_since + 1s = 有后续入队迹象
    _write_stale_world(
        tmp_path, pid=_dead_pid(), hb_overrides={"last_message_ts": time.time() - 150.0}
    )
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "subsequent_message" in detail


# --- 矩阵 G：心跳未 stale / 时点非法 → confirmed_busy --------------------------


def test_matrix_g_fresh_heartbeat_stays_busy(tmp_path: Path) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid(), hb_overrides={"ts": time.time() - 5.0})
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "heartbeat_fresh" in detail


def test_matrix_g_future_heartbeat_stays_busy(tmp_path: Path) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid(), hb_overrides={"ts": time.time() + 30.0})
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "heartbeat_ts_invalid" in detail


def test_matrix_g_missing_ts_stays_busy(tmp_path: Path) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid(), hb_overrides={"ts": None})
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "heartbeat_ts_invalid" in detail


# --- 矩阵 H：PID 非法 / PermissionError → confirmed_busy -----------------------


@pytest.mark.parametrize("pid", [0, -1, "1391545", None])
def test_matrix_h_invalid_pid_stays_busy(tmp_path: Path, pid: int | str | None) -> None:
    _write_stale_world(tmp_path, pid=pid)
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "pid_invalid" in detail


def test_matrix_h_permission_error_stays_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_stale_world(tmp_path, pid=os.getpid())

    def _raise_permission(pid: int, sig: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "kill", _raise_permission)
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "pid_alive_or_unknown" in detail


# --- 矩阵 I：PID 复用仍存活（os.kill 无异常）→ confirmed_busy ------------------


def test_matrix_i_reused_pid_alive_stays_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_stale_world(tmp_path, pid=123456)
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)  # kill(0) 成功 = 存在
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "pid_alive_or_unknown" in detail


# --- 矩阵 J：web 持 run lock 时 all 仍 busy（即使 feishu 已按证据放行）---------


def test_matrix_j_web_run_lock_still_busy_overall(tmp_path: Path) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid())
    _write_idle_wecom_heartbeat(tmp_path)
    sessions = tmp_path / "data" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    lock = sessions / "sid-matrix.run.lock"
    lock.write_text("", encoding="utf-8")
    with lock.open("r") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            state, detail = _state(tmp_path, target="all")
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    assert state == "confirmed_busy"
    assert "active run locks" in detail
    assert "feishu busy" not in detail  # feishu 证据链已放行，不构成忙碌理由


# --- history 连续快照门槛（fail-closed）---------------------------------------


def test_history_missing_stays_busy(tmp_path: Path) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid(), omit_history=True)
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_unreadable" in detail


def test_history_too_few_rows_stays_busy(tmp_path: Path) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid(), history_rows=2)
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_insufficient" in detail


def test_history_subsequent_message_in_snapshots_stays_busy(tmp_path: Path) -> None:
    # history 最新一快照 last_message_ts 后移（入队观察）与主心跳不一致 → busy
    heartbeat = _write_stale_world(tmp_path, pid=_dead_pid())
    later = float(heartbeat["last_message_ts"]) + 60.0
    (tmp_path / "data" / "feishu_heartbeat_history.jsonl").write_text(
        "\n".join(
            json.dumps(
                {**heartbeat, "ts": heartbeat["ts"] - 30.0 * (2 - i), "last_message_ts": later}
            )
            for i in range(3)
        )
        + "\n",
        encoding="utf-8",
    )
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_state_changed" in detail


def test_history_pid_mismatch_stays_busy(tmp_path: Path) -> None:
    # history 显示另一 pid 写出同一 processing（PID 复用观察）→ busy
    _write_stale_world(tmp_path, pid=_dead_pid(), history_overrides=[{}, {}, {"pid": os.getpid()}])
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_state_changed" in detail


def test_history_corrupt_last_row_stays_busy(tmp_path: Path) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid())
    with open(
        tmp_path / "data" / "feishu_heartbeat_history.jsonl", "a", encoding="utf-8"
    ) as handle:
        handle.write("{corrupt\n")
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_row_malformed" in detail


# --- 既有语义回归：探测缺失仍 unconfirmable；wecom 分支不受影响 -----------------


def test_missing_heartbeat_keeps_unconfirmable_semantics(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    state, _ = _state(tmp_path)
    assert state == "unconfirmable"  # 探测能力不足 ≠ 忙碌，语义保持不变


def test_wecom_busy_branch_untouched(tmp_path: Path) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid())
    (tmp_path / "data" / "wecom_heartbeat.json").write_text(
        json.dumps({"processing_msg_id": "wecom_msg", "queue_depth": 0}), encoding="utf-8"
    )
    state, detail = _state(tmp_path, target="all")
    assert state == "confirmed_busy"
    assert "wecom busy" in detail
    assert "feishu busy" not in detail  # feishu 已按证据链放行，wecom 仍独立判定


# --- M2-2 复检 P1-A：父侧真实反例——queue_depth 缺失不得静默归零 -----------------


def test_regression_parent_case_a_missing_queue_depth_stays_busy(tmp_path: Path) -> None:
    """父侧反例 A：主心跳+history 3 行全部缺 queue_depth，其余证据链齐全.

    旧行为 ``int(None or 0)`` 静默归零 → confirmed_idle（假忙解除误放行）。
    """
    heartbeat = _write_stale_world(tmp_path, pid=_dead_pid())
    hb_path = tmp_path / "data" / "feishu_heartbeat.json"
    hb = json.loads(hb_path.read_text(encoding="utf-8"))
    hb.pop("queue_depth")
    hb_path.write_text(json.dumps(hb), encoding="utf-8")
    hist_path = tmp_path / "data" / "feishu_heartbeat_history.jsonl"
    rows = [json.loads(x) for x in hist_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    for row in rows:
        row.pop("queue_depth", None)
    hist_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "queue_depth" in detail
    # 反例 A 的完整特征仍在场：processing 冻结 + 死 PID + 补偿齐全——但 queue_depth
    # 无效必须无条件 busy，不进入 stale 恢复证据链
    assert heartbeat["processing_msg_id"] == MSG_ID


def _valid_comp_record() -> dict:
    """与 _write_stale_world 默认补偿同构的合法记录（供逐字段剔除变体）."""
    return {
        "receive_id": "oc_matrix",
        "reply_type": "chat_id",
        "interrupt_cause": "crash",
        "interrupted_at": _iso_local(time.time() + 1.0),
        "context_ref": "",
        "msg_id": MSG_ID,
    }


_NO_COMP_DETAIL = "compensation_unreadable"  # JSONL 整体解析失败 → 证据不足标签


def _no_comp_detail() -> str:
    return _NO_COMP_DETAIL


@pytest.mark.parametrize(
    "bad_queue_depth",
    [None, "", "0", "5", True, False, -1, -0.5, 1.5, 0.0, [], {}],
    ids=[
        "none",
        "empty-str",
        "str0",
        "str5",
        "true",
        "false",
        "neg-int",
        "neg-float",
        "float",
        "float-zero",
        "list",
        "dict",
    ],
)
def test_top_queue_depth_invalid_values_fail_closed(tmp_path: Path, bad_queue_depth) -> None:
    """顶层 queue_depth 缺失/None/空串/字符串/float/bool/负数/非数 → busy 且不抛异常."""
    _write_stale_world(tmp_path, pid=_dead_pid(), hb_overrides={"queue_depth": bad_queue_depth})
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "queue_depth" in detail
    assert "无效" in detail


def test_top_queue_depth_invalid_even_when_idle_processing(
    tmp_path: Path,
) -> None:
    """processing 已空但 queue_depth 无效：仍必须 busy（写坏的心跳 ≠ 空闲证据）."""
    _write_stale_world(
        tmp_path,
        pid=_dead_pid(),
        hb_overrides={"queue_depth": None, "processing_msg_id": ""},
    )
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "queue_depth" in detail


def test_wecom_loose_queue_depth_semantics_untouched(tmp_path: Path) -> None:
    """边界对照：WeCom 分支保持既有宽松语义（缺 queue_depth → 0，不判忙）."""
    _write_stale_world(tmp_path, pid=_dead_pid())
    (tmp_path / "data" / "wecom_heartbeat.json").write_text(
        json.dumps({"processing_msg_id": ""}), encoding="utf-8"
    )
    state, detail = _state(tmp_path, target="wecom")
    assert state == "confirmed_idle"
    assert "wecom busy" not in detail


# --- M2-2 复检 P1-B：父侧真实反例——JSONL 补偿缺字段不得默认补全 ---------------


def test_regression_parent_case_b_jsonl_minimal_fields_stays_busy(
    tmp_path: Path,
) -> None:
    """父侧反例 B：补偿行只有 receive_id/msg_id/interrupted_at → 必须 busy.

    旧行为默认补 chat_id/CRASH → 记录"合法" → 假忙解除误放行。
    """
    now = time.time()
    _write_stale_world(
        tmp_path,
        pid=_dead_pid(),
        comp_lines=[
            json.dumps(
                {
                    "receive_id": "oc_matrix",
                    "msg_id": MSG_ID,
                    "interrupted_at": _iso_local(now + 1.0),
                }
            )
        ],
    )
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "compensation_unreadable" in detail


def test_jsonl_missing_reply_type_stays_busy(tmp_path: Path) -> None:
    record = _valid_comp_record()
    record.pop("reply_type")
    _write_stale_world(tmp_path, pid=_dead_pid(), comp_lines=[json.dumps(record)])
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert _no_comp_detail() in detail


def test_jsonl_missing_interrupt_cause_stays_busy(tmp_path: Path) -> None:
    record = _valid_comp_record()
    record.pop("interrupt_cause")
    _write_stale_world(tmp_path, pid=_dead_pid(), comp_lines=[json.dumps(record)])
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert _no_comp_detail() in detail


def test_jsonl_missing_both_stays_busy(tmp_path: Path) -> None:
    record = _valid_comp_record()
    record.pop("reply_type")
    record.pop("interrupt_cause")
    _write_stale_world(tmp_path, pid=_dead_pid(), comp_lines=[json.dumps(record)])
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert _no_comp_detail() in detail


# --- M2-2 复检：NaN/±Inf 时戳不得绕过 stale/fresh 比较 --------------------------


@pytest.mark.parametrize(
    "bad_field",
    ["ts", "processing_since", "last_message_ts"],
    ids=["hb-ts", "processing-since", "last-message-ts"],
)
def test_nonfinite_timestamps_stay_busy(tmp_path: Path, bad_field: str) -> None:
    """NaN 绕过全部数值比较（NaN>x / NaN<=0 / now-NaN<stale 全 False）→ 必须 busy."""
    for bad_value in (float("nan"), float("inf"), float("-inf")):
        world = tmp_path / f"case-{bad_field}-{bad_value!r}"
        _write_stale_world(world, pid=_dead_pid(), hb_overrides={bad_field: bad_value})
        state, _ = _state(world)
        assert state == "confirmed_busy", f"{bad_field}={bad_value!r}"


def test_history_nonfinite_ts_stays_busy(tmp_path: Path) -> None:
    _write_stale_world(
        tmp_path,
        pid=_dead_pid(),
        history_overrides=[{"ts": float("nan")}, {}, {}],
    )
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_ts_invalid" in detail


# --- M2-2 复检：history 快照 ts 链与字段一致性加强 ------------------------------


def test_history_missing_queue_depth_stays_busy(tmp_path: Path) -> None:
    """history 行缺 queue_depth：不得 int(None or 0) 归零后放行."""
    _write_stale_world(tmp_path, pid=_dead_pid())
    hist_path = tmp_path / "data" / "feishu_heartbeat_history.jsonl"
    rows = [json.loads(x) for x in hist_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows[0].pop("queue_depth", None)
    hist_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_queue_depth_invalid" in detail


@pytest.mark.parametrize(
    "history_overrides,expected_tag",
    [
        ([{"ts": None}], "history_ts_invalid"),
        ([{"ts": -1.0}], "history_ts_invalid"),
    ],
    ids=["ts-null", "ts-negative"],
)
def test_history_row_ts_invalid_stays_busy(
    tmp_path: Path, history_overrides: list[dict], expected_tag: str
) -> None:
    _write_stale_world(tmp_path, pid=_dead_pid(), history_overrides=history_overrides)
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert expected_tag in detail


def test_history_duplicate_ts_stays_busy(tmp_path: Path) -> None:
    """相邻两行 ts 相同 → 非严格递增 → 快照链不可信."""
    heartbeat = _write_stale_world(tmp_path, pid=_dead_pid())
    hb_ts = heartbeat["ts"]
    _write_stale_world(
        tmp_path,
        pid=_dead_pid(),
        history_overrides=[{"ts": hb_ts - 30.0}, {"ts": hb_ts - 30.0}, {}],
    )
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_ts_not_monotonic" in detail


def test_history_non_monotonic_ts_stays_busy(tmp_path: Path) -> None:
    heartbeat = _write_stale_world(tmp_path, pid=_dead_pid())
    hb_ts = heartbeat["ts"]
    _write_stale_world(
        tmp_path,
        pid=_dead_pid(),
        history_overrides=[{"ts": hb_ts}, {}, {}],
    )
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_ts_not_monotonic" in detail


def test_history_gap_too_large_stays_busy(tmp_path: Path) -> None:
    """相邻间隔超过 2×watchdog 周期+容差（65s）→ 快照链断裂（挂钟暂停等）."""
    heartbeat = _write_stale_world(tmp_path, pid=_dead_pid())
    hb_ts = heartbeat["ts"]
    _write_stale_world(
        tmp_path,
        pid=_dead_pid(),
        history_overrides=[{"ts": hb_ts - 30.0 - 200.0}, {}, {}],
    )
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_gap_too_large" in detail


def test_history_latest_ts_mismatch_stays_busy(tmp_path: Path) -> None:
    """最新行 ts 与主心跳 ts 不精确一致 → 主文件与 history 非同 tick 写出."""
    heartbeat = _write_stale_world(tmp_path, pid=_dead_pid())
    hb_ts = heartbeat["ts"]
    _write_stale_world(
        tmp_path,
        pid=_dead_pid(),
        history_overrides=[{}, {}, {"ts": hb_ts - 29.5}],
    )
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_latest_mismatch" in detail


def test_history_processing_since_mismatch_stays_busy(tmp_path: Path) -> None:
    heartbeat = _write_stale_world(tmp_path, pid=_dead_pid())
    _write_stale_world(
        tmp_path,
        pid=_dead_pid(),
        history_overrides=[{}, {}, {"processing_since": heartbeat["processing_since"] + 1.0}],
    )
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_state_changed" in detail


def test_history_missing_ts_row_stays_busy(tmp_path: Path) -> None:
    """history 行完全缺 ts 字段 → ts 链不完整 → busy."""
    _write_stale_world(tmp_path, pid=_dead_pid())
    hist_path = tmp_path / "data" / "feishu_heartbeat_history.jsonl"
    rows = [json.loads(x) for x in hist_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows[1].pop("ts", None)
    hist_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    state, detail = _state(tmp_path)
    assert state == "confirmed_busy"
    assert "history_ts_invalid" in detail
