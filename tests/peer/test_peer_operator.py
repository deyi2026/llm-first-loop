"""Lane-C（快照确认边界）：R37 快照绑定与票据消费原子性。

设计依据：docs/design/LFL_Peer_Requirements_Implementation_Design_2026-11-11.md
- §6.3 覆盖确认：预览快照绑定进票据，执行前重查；
- R37/A05（§15 Q6）：快照 SHALL 同时绑定原文件字节摘要与权限位，
  执行前重查任一不符即冲突，不静默沿用变化后的权限；
- A07（§15）：票据一次性消费由 ``os.replace`` 原子认领兜底，此处补并发负例实测。

口径：本文件只测 OperatorChannel 边界（预览签票 → 执行前重查 → 一次性消费），
不经过 PeerService/executor（装配属其它 lane）。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading

import pytest

from llm_loop.peer.errors import PeerError
from llm_loop.peer.operator import OperatorChannel, SupervisionTicket

NODE = "deepin-01"
PARAMS_DIGEST = "p" * 64
TASK_ID = "tsk_snap00001"


def _channel(tmp_path):
    return OperatorChannel(tmp_path / "peer")


def _issue(channel, task_id=TASK_ID, *, target=None, digest=PARAMS_DIGEST):
    return channel.issue(
        task_id=task_id,
        node_id=NODE,
        kind="fs.write",
        params_digest=digest,
        issued_by="tester",
        ttl_s=60,
        target=target,
    )


def _existing_target(tmp_path, *, content=b"hello", mode=0o644):
    target = tmp_path / "out.txt"
    target.write_bytes(content)
    target.chmod(mode)
    return target


# ---- 任务②：快照绑定内容摘要（缺则补）与权限位（任务①） --------------------
def test_preview_binds_digest_and_mode_into_ticket(tmp_path):
    """预览签票时捕获 sha256+权限位并持久化进票据 JSON（R37 快照定义）。"""
    from llm_loop.peer.operator import TargetSnapshot  # Lane-C 新增 API

    target = _existing_target(tmp_path)
    channel = _channel(tmp_path)
    ticket = _issue(channel, target=str(target))

    assert ticket.target_snapshot is not None
    snap = ticket.target_snapshot
    assert isinstance(snap, TargetSnapshot)
    assert snap.exists and snap.path == str(target)
    assert snap.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert snap.mode == 0o644
    assert snap.size == 5

    # 快照必须落盘：确认/执行是另一次调用甚至另一个进程，内存里的不算数
    raw = json.loads(channel._path(TASK_ID).read_text(encoding="utf-8"))  # noqa: SLF001
    assert raw["target_snapshot"]["sha256"] == snap.sha256
    assert raw["target_snapshot"]["mode"] == 0o644


def test_chmod_after_preview_conflicts_at_consume(tmp_path):
    """任务①（R37 核心，现红）：预览后仅 chmod，确认时报冲突而非静默沿用。"""
    target = _existing_target(tmp_path, mode=0o644)
    channel = _channel(tmp_path)
    _issue(channel, target=str(target))

    os.chmod(target, 0o600)  # 预览后权限位变化，字节不变
    with pytest.raises(PeerError) as err:
        channel.consume(TASK_ID, params_digest=PARAMS_DIGEST)
    assert err.value.reason_code == "supervision_ticket_mismatch"
    assert "权限位" in err.value.detail

    # 冲突不烧票：票据保留（批准物证可查），consumed 不存在，目标无副作用
    assert channel._path(TASK_ID).exists()  # noqa: SLF001
    assert not channel._consumed_path(TASK_ID).exists()  # noqa: SLF001
    assert target.read_bytes() == b"hello"
    assert (os.stat(target).st_mode & 0o777) == 0o600  # 不顺手改回权限


def test_content_change_after_preview_conflicts_at_consume(tmp_path):
    """任务②：预览后内容变化，确认时报冲突（内容摘要绑定）。"""
    target = _existing_target(tmp_path)
    channel = _channel(tmp_path)
    _issue(channel, target=str(target))

    target.write_bytes(b"tampered after preview")
    with pytest.raises(PeerError) as err:
        channel.consume(TASK_ID, params_digest=PARAMS_DIGEST)
    assert err.value.reason_code == "supervision_ticket_mismatch"
    assert "内容摘要" in err.value.detail
    assert channel._path(TASK_ID).exists()  # noqa: SLF001


def test_unchanged_target_consumes_exactly_once(tmp_path):
    """绿路径：摘要与权限位都没变，消费成功且对目标零副作用。"""
    target = _existing_target(tmp_path)
    channel = _channel(tmp_path)
    _issue(channel, target=str(target))

    consumed = channel.consume(TASK_ID, params_digest=PARAMS_DIGEST)
    assert isinstance(consumed, SupervisionTicket)
    assert consumed.target_snapshot is not None
    assert consumed.target_snapshot.mode == 0o644
    assert channel._consumed_path(TASK_ID).exists()  # noqa: SLF001
    assert target.read_bytes() == b"hello"
    assert (os.stat(target).st_mode & 0o777) == 0o644

    with pytest.raises(PeerError) as err:
        channel.consume(TASK_ID, params_digest=PARAMS_DIGEST)
    assert err.value.reason_code == "supervision_ticket_consumed"


# ---- 快照边界扩展：新建目标的出现/消失 ------------------------------------
def test_newfile_target_appearing_after_preview_conflicts(tmp_path):
    """预览为"新建"，确认前目标被外部创建 → 冲突（A03 原文件变化）。"""
    target = tmp_path / "fresh.txt"
    channel = _channel(tmp_path)
    ticket = _issue(channel, target=str(target))
    assert ticket.target_snapshot is not None and not ticket.target_snapshot.exists

    target.write_bytes(b"unexpected creator")
    with pytest.raises(PeerError) as err:
        channel.consume(TASK_ID, params_digest=PARAMS_DIGEST)
    assert err.value.reason_code == "supervision_ticket_mismatch"
    assert "目标已出现" in err.value.detail


def test_newfile_target_still_absent_consumes_ok(tmp_path):
    """预览为"新建"且确认时仍不存在 → 正常消费（不误伤新建路径）。"""
    target = tmp_path / "fresh.txt"
    channel = _channel(tmp_path)
    _issue(channel, target=str(target))

    consumed = channel.consume(TASK_ID, params_digest=PARAMS_DIGEST)
    assert consumed.task_id == TASK_ID
    assert not target.exists()


def test_existing_target_disappearing_after_preview_conflicts(tmp_path):
    """预览为覆盖，确认前目标被删除 → 冲突（执行语义已从覆盖变成新建）。"""
    target = _existing_target(tmp_path)
    channel = _channel(tmp_path)
    _issue(channel, target=str(target))

    target.unlink()
    with pytest.raises(PeerError) as err:
        channel.consume(TASK_ID, params_digest=PARAMS_DIGEST)
    assert err.value.reason_code == "supervision_ticket_mismatch"
    assert "目标已消失" in err.value.detail


# ---- 兼容与 fail-closed ----------------------------------------------------
def test_ticket_without_target_keeps_legacy_shape(tmp_path):
    """不传 target（service/旧 CLI 现行调用面）：票据形状不变，行为不变。"""
    channel = _channel(tmp_path)
    ticket = _issue(channel)
    assert ticket.target_snapshot is None
    raw = json.loads(channel._path(TASK_ID).read_text(encoding="utf-8"))  # noqa: SLF001
    assert "target_snapshot" not in raw

    consumed = channel.consume(TASK_ID, params_digest=PARAMS_DIGEST)
    assert consumed.task_id == TASK_ID


def test_conflict_enforced_from_persisted_snapshot(tmp_path):
    """冲突裁决以落盘快照为准：篡改票据 JSON 的权限位即被识破。"""
    target = _existing_target(tmp_path, mode=0o644)
    channel = _channel(tmp_path)
    _issue(channel, target=str(target))

    ticket_path = channel._path(TASK_ID)  # noqa: SLF001
    raw = json.loads(ticket_path.read_text(encoding="utf-8"))
    raw["target_snapshot"]["mode"] = 0o400
    ticket_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PeerError) as err:
        channel.consume(TASK_ID, params_digest=PARAMS_DIGEST)
    assert err.value.reason_code == "supervision_ticket_mismatch"
    assert "权限位" in err.value.detail


def test_non_regular_or_empty_target_refused_at_issue(tmp_path):
    """目录/符号链接/空串目标在签票时明确拒绝，不产出模糊快照。"""
    channel = _channel(tmp_path)
    directory = tmp_path / "adir"
    directory.mkdir()
    with pytest.raises(PeerError) as err:
        _issue(channel, target=str(directory))
    assert err.value.reason_code == "params_schema_invalid"

    real = tmp_path / "out.txt"  # 目录用例之后补一个真文件作为符号链接目标
    real.write_bytes(b"anchor")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    with pytest.raises(PeerError) as err:
        _issue(channel, target=str(link))
    assert err.value.reason_code == "params_schema_invalid"

    with pytest.raises(PeerError) as err:
        _issue(channel, target="   ")
    assert err.value.reason_code == "params_schema_invalid"
    # 拒绝时不得留下半张票据
    assert not channel._path(TASK_ID).exists()  # noqa: SLF001


# ---- 任务③：票据并发/跨实例消费只成功一次 ---------------------------------
def test_concurrent_consume_same_ticket_exactly_one_wins(tmp_path, monkeypatch):
    """并发负例：两个消费者同时越过前置检查、同刻争夺 os.replace，只成功一次。

    设计 §15 声称该竞态由 ``os.replace`` 原子性兜底（第二消费者
    ``FileNotFoundError`` → ``supervision_ticket_consumed``），此处用 barrier
    把两个线程同步到 replace 同一刻做实测。
    """
    channel = _channel(tmp_path)
    _issue(channel)
    barrier = threading.Barrier(2)
    real_replace = os.replace

    def rendezvous_replace(src, dst):
        barrier.wait(timeout=10)  # 双方都完成 load/前置检查后才放行真 replace
        return real_replace(src, dst)

    monkeypatch.setattr("llm_loop.peer.operator.os.replace", rendezvous_replace)

    results: list[SupervisionTicket] = []
    errors: list[PeerError] = []

    def worker() -> None:
        try:
            results.append(channel.consume(TASK_ID, params_digest=PARAMS_DIGEST))
        except PeerError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads)

    assert len(results) == 1
    assert isinstance(results[0], SupervisionTicket)
    assert len(errors) == 1
    assert errors[0].reason_code == "supervision_ticket_consumed"
    assert channel._consumed_path(TASK_ID).exists()  # noqa: SLF001


def test_second_cli_instance_consume_fails(tmp_path):
    """顺序负例（双 CLI 实例）：第一个实例消费后，第二个实例必然失败。"""
    data_dir = tmp_path / "peer"
    first = OperatorChannel(data_dir)
    second = OperatorChannel(data_dir)
    _issue(first)

    consumed = first.consume(TASK_ID, params_digest=PARAMS_DIGEST)
    assert consumed.task_id == TASK_ID

    with pytest.raises(PeerError) as err:
        second.consume(TASK_ID, params_digest=PARAMS_DIGEST)
    assert err.value.reason_code == "supervision_ticket_consumed"
