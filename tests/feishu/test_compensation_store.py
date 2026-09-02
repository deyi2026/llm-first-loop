"""中断补偿底座单元测试（tasks 6.1；FTR-COMP-1/4、FTR-DFX-02/03/08）.

覆盖：
- CompensationStore：append/read_all 六字段往返、remove_entry 幂等剔除、
  单行损坏跳过隔离、字段非法 ValueError、OSError fail-open。
- 旧单文件 feishu_interrupted.json 迁移：无损迁移 + 旧文件删除（ADR-1）。
- InterruptionNotifier：成功即送、失败/超时落兜底、fallback=False 不双落。
"""

from __future__ import annotations

import json
import time

import pytest

from llm_loop.feishu.compensation import (
    CRASH,
    QUEUE_FULL,
    WATCHDOG_EXIT,
    CompensationStore,
    InterruptionCompensationRecord,
    InterruptionNotifier,
)


def _rec(**kw) -> InterruptionCompensationRecord:
    base = {
        "receive_id": "oc_base",
        "reply_type": "chat_id",
        "interrupt_cause": CRASH,
        "context_ref": "sid_x",
        "msg_id": "om_1",
    }
    base.update(kw)
    return InterruptionCompensationRecord(**base)


def _store(tmp_path) -> CompensationStore:
    return CompensationStore(
        tmp_path / "feishu_compensation.jsonl",
        legacy_path=tmp_path / "feishu_interrupted.json",
    )


# ── CompensationStore 基础 ──


def test_append_read_roundtrip_six_fields(tmp_path):
    store = _store(tmp_path)
    store.append(_rec())
    store.append(_rec(receive_id="oc_2", interrupt_cause=QUEUE_FULL, msg_id="om_2"))

    recs = store.read_all()

    assert len(recs) == 2
    assert recs[0].receive_id == "oc_base"
    assert recs[0].reply_type == "chat_id"
    assert recs[0].interrupt_cause == CRASH
    assert recs[0].context_ref == "sid_x"
    assert recs[0].msg_id == "om_1"
    assert recs[0].interrupted_at, "中断时点应自动填充"
    assert recs[1].interrupt_cause == QUEUE_FULL


def test_remove_entry_idempotent(tmp_path):
    store = _store(tmp_path)
    r1, r2 = _rec(), _rec(receive_id="oc_2", msg_id="om_2")
    store.append(r1)
    store.append(r2)

    store.remove_entry(r1.key())

    recs = store.read_all()
    assert len(recs) == 1 and recs[0].key() == r2.key()
    # 幂等：重复剔除同 key 不抛异常、不误删
    store.remove_entry(r1.key())
    assert len(store.read_all()) == 1
    store.remove_entry("no:such:key")
    assert len(store.read_all()) == 1


def test_corrupt_line_isolated_not_blocking(tmp_path):
    store = _store(tmp_path)
    store.append(_rec())
    with (tmp_path / "feishu_compensation.jsonl").open("a", encoding="utf-8") as f:
        f.write("{{{损坏行 not-json\n")
    store.append(_rec(receive_id="oc_3", msg_id="om_3"))

    recs = store.read_all()

    assert [r.msg_id for r in recs] == ["om_1", "om_3"], "损坏行应跳过隔离，不阻断其余"


def test_field_invalid_values_raise():
    with pytest.raises(ValueError):
        _rec(interrupt_cause="bogus_cause")
    with pytest.raises(ValueError):
        _rec(reply_type="user_id")
    with pytest.raises(ValueError):
        _rec(receive_id="")


def test_oserror_fail_open(tmp_path):
    dir_as_file = tmp_path / "not_a_file"
    dir_as_file.mkdir()
    store = CompensationStore(dir_as_file, legacy_path=tmp_path / "none.json")

    store.append(_rec())  # IsADirectoryError（OSError 子类）→ 仅告警不抛

    assert store.read_all() == []


# ── 旧单文件迁移（ADR-1）──


def test_legacy_single_file_migrated_lossless(tmp_path):
    legacy = tmp_path / "feishu_interrupted.json"
    legacy.write_text(
        json.dumps(
            {
                "reply_id": "oc_legacy",
                "reply_type": "chat_id",
                "msg_id": "om_legacy",
                "interrupted_at": "2026-08-30T10:00:00",
            }
        ),
        encoding="utf-8",
    )
    store = _store(tmp_path)

    recs = store.read_all()  # 首次读取触发迁移

    assert len(recs) == 1
    assert recs[0].receive_id == "oc_legacy", "旧 reply_id 应无损映射为 receive_id"
    assert recs[0].interrupt_cause == CRASH, "旧记录无原因字段，如实归类 crash"
    assert recs[0].msg_id == "om_legacy"
    assert recs[0].interrupted_at == "2026-08-30T10:00:00"
    assert not legacy.exists(), "旧文件迁移后应删除"
    assert (tmp_path / "feishu_compensation.jsonl").exists()


def test_legacy_corrupt_kept_not_migrated(tmp_path):
    legacy = tmp_path / "feishu_interrupted.json"
    legacy.write_text("not-json", encoding="utf-8")
    store = _store(tmp_path)

    assert store.read_all() == [], "旧文件损坏 → 迁移失败 fail-open，零记录"
    assert legacy.exists(), "迁移失败保留旧文件（不丢数据）"


# ── InterruptionNotifier ──


def _notifier(tmp_path, send_fn, **kw) -> tuple[InterruptionNotifier, CompensationStore]:
    store = _store(tmp_path)
    return InterruptionNotifier(send_fn, store, **kw), store


def test_notifier_success_no_fallback(tmp_path):
    sent: list[tuple[str, str, str]] = []

    def _send(rid, text, rtype):
        sent.append((rid, text, rtype))
        return True

    notifier, store = _notifier(tmp_path, _send)

    assert notifier.notify("oc_a", "chat_id", CRASH, "（程序提示）x") is True
    assert sent and sent[0][0] == "oc_a"
    assert store.read_all() == [], "成功即送不应落兜底记录"


def test_notifier_send_false_falls_back(tmp_path):
    notifier, store = _notifier(tmp_path, lambda rid, text, rtype: False)

    assert notifier.notify("oc_a", "chat_id", QUEUE_FULL, "（程序提示）x") is False
    recs = store.read_all()
    assert len(recs) == 1 and recs[0].interrupt_cause == QUEUE_FULL


def test_notifier_timeout_falls_back(tmp_path):
    def _slow(rid, text, rtype):
        time.sleep(1.5)
        return True

    notifier, store = _notifier(tmp_path, _slow, timeout_s=0.2)

    t0 = time.monotonic()
    assert notifier.notify("oc_a", "chat_id", CRASH, "（程序提示）x") is False
    assert time.monotonic() - t0 < 1.2, "1s 上限：不得同步等满慢发送"
    assert len(store.read_all()) == 1


def test_notifier_fallback_false_no_duplicate(tmp_path):
    notifier, store = _notifier(tmp_path, lambda rid, text, rtype: False)
    store.append(_rec(receive_id="oc_a", interrupt_cause=WATCHDOG_EXIT))  # 调用方已落

    ok = notifier.notify("oc_a", "chat_id", WATCHDOG_EXIT, "（程序提示）x", fallback=False)

    assert ok is False
    assert len(store.read_all()) == 1, "fallback=False 失败不得再落兜底（防双落）"
