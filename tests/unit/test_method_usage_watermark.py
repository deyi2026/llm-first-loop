"""Usage-ledger watermark integrity: fsync'd appends must not vanish silently.

EVO-20261010 usage-ledger loss: a git tree-clean revert destroyed an
already-fsync'd, receipt-confirmed record_use append because usage.jsonl was
simultaneously a runtime append-only ledger and a git-tracked file. The
monotonic line-count watermark never gates writes; it only makes such external
truncation observable at the next integrity check.
"""

from __future__ import annotations

import json
import logging

from llm_loop.methods.store import MethodStore

from tests.unit.test_method_store_durability import BODY, _save

EP = "episode:00000000-0000-0000-0000-000000000000:0:deadbeef"


def test_watermark_detects_external_truncation(tmp_path, caplog):
    store = MethodStore(tmp_path)
    rec = _save(store)
    store.record_use(rec.method_ref, episode_ref=EP, decision="applied", note="one")
    store.record_use(rec.method_ref, episode_ref=EP, decision="adapted", note="two")
    watermark = json.loads((tmp_path / ".usage_watermark.json").read_text(encoding="utf-8"))
    assert watermark["count"] == 2

    # external actor truncates the ledger (e.g. git revert of uncommitted appends)
    ledger = tmp_path / "usage.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines(keepends=True)
    ledger.write_text("".join(lines[:1]), encoding="utf-8")

    fresh = MethodStore(tmp_path)
    with caplog.at_level(logging.ERROR, logger="llm_loop.methods.store"):
        report = fresh.check_usage_integrity()
    assert report["monitored"] is True
    assert report["lost"] == 1
    assert report["watermark_count"] == 2
    assert report["current_count"] == 1
    assert any("lost 1 entry" in rec.message for rec in caplog.records)


def test_watermark_never_ratchets_down(tmp_path):
    store = MethodStore(tmp_path)
    rec = _save(store)
    for decision in ("applied", "adapted", "applied"):
        store.record_use(rec.method_ref, episode_ref=EP, decision=decision, note="n")

    # external truncation to empty, then one legitimate new append
    (tmp_path / "usage.jsonl").write_text("", encoding="utf-8")
    store2 = MethodStore(tmp_path)
    store2.record_use(rec.method_ref, episode_ref=EP, decision="applied", note="after loss")

    watermark = json.loads((tmp_path / ".usage_watermark.json").read_text(encoding="utf-8"))
    assert watermark["count"] == 3  # floor kept at historical high-water mark
    report = store2.check_usage_integrity()
    assert report["lost"] == 2
    assert report["current_count"] == 1


def test_unmonitored_store_reports_clean(tmp_path):
    store = MethodStore(tmp_path)
    assert store.check_usage_integrity() == {"monitored": False, "lost": 0}
