"""merge_queue 失败分诊与 R5 分诊视图（DESIGN-20261114 §6 验收表）."""

from __future__ import annotations

import json

from llm_loop.introspection.goal_coordination import (
    _QUEUE_BUCKETS,
    _collect_merge_queue,
    render_coordination,
)
from llm_loop.introspection.merge_queue import (
    FAILURE_CLASSES,
    MergeQueueStore,
    check_base_main_current,
    classify_failure,
)


def _chk(name: str, reason: str, evidence: dict | None = None) -> dict:
    return {"check": name, "verdict": "fail", "reason_code": reason, "evidence": evidence or {}}


def _pass(name: str) -> dict:
    return {"check": name, "verdict": "pass", "reason_code": "", "evidence": {}}


def _entry(*checks: dict, reasons: list[str] | None = None) -> dict:
    return {"last_preflight": {"checks": list(checks)}, "failure_reasons": reasons or []}


# ---- 单类映射 ----


def test_base_stale_is_needs_rebase_not_retryable():
    d = classify_failure(_entry(_chk("base_main_current", "base_stale")))
    assert d["primary_check"] == "base_main_current"
    assert d["failure_class"] == "needs_rebase"
    assert d["retryable"] is False


def test_main_head_unknown_config_error():
    d = classify_failure(
        _entry(
            _chk(
                "base_main_current",
                "main_head_unknown",
                {"rc": 128, "stderr_tail": "fatal: not a git repository"},
            )
        )
    )
    assert d["failure_class"] == "env_config"
    assert d["retryable"] is False


def test_main_head_unknown_transient():
    d = classify_failure(
        _entry(
            _chk(
                "base_main_current",
                "main_head_unknown",
                {"rc": 128, "stderr_tail": "fatal: Unable to create index.lock: File exists"},
            )
        )
    )
    assert d["failure_class"] == "env_transient"
    assert d["retryable"] is True


def test_main_head_unknown_without_rc_fails_closed():
    d = classify_failure(
        _entry(_chk("base_main_current", "main_head_unknown", {"entry_base": "x"}))
    )
    assert d["failure_class"] == "env_config"
    assert "rc_missing" in d["evidence_hint"]
    assert d["retryable"] is False


def test_cascade_merge_tree_not_double_counted():
    d = classify_failure(
        _entry(
            _chk("base_main_current", "main_head_unknown", {"rc": 128, "stderr_tail": "boom"}),
            _chk("merge_tree_clean", "merge_tree_unavailable", {"rc": 2, "stderr_tail": "x"}),
        )
    )
    assert d["primary_check"] == "base_main_current"
    assert d["primary_reason"] == "main_head_unknown"
    assert d["cascade_of"] == "main_head_unknown"


def test_merge_tree_unavailable_independent_is_transient():
    d = classify_failure(
        _entry(
            _pass("base_main_current"),
            _chk("merge_tree_clean", "merge_tree_unavailable", {"rc": 2, "stderr_tail": "weird"}),
        )
    )
    assert d["primary_check"] == "merge_tree_clean"
    assert d["failure_class"] == "env_transient"


def test_verify_codes_are_verify_missing():
    for code in ("verify_required", "verify_stale", "verify_invalid", "verify_expired"):
        d = classify_failure(
            _entry(
                _pass("base_main_current"),
                _pass("merge_tree_clean"),
                _pass("paths_disjoint"),
                _chk("verify_covers_base", code),
            )
        )
        assert d["failure_class"] == "verify_missing", code
        assert d["retryable"] is False


def test_verify_layer_not_enabled_is_config():
    d = classify_failure(
        _entry(
            _pass("base_main_current"),
            _pass("merge_tree_clean"),
            _pass("paths_disjoint"),
            _chk("verify_covers_base", "verify_layer_not_enabled"),
        )
    )
    assert d["failure_class"] == "env_config"


def test_true_conflict_never_retryable():
    d = classify_failure(
        _entry(
            _pass("base_main_current"),
            _chk("merge_tree_clean", "merge_conflict", {"conflicting_paths": ["a.py"]}),
        )
    )
    assert d["failure_class"] == "true_conflict"
    assert d["retryable"] is False


def test_paths_overlap_needs_serialize():
    d = classify_failure(
        _entry(
            _pass("base_main_current"),
            _pass("merge_tree_clean"),
            _chk("paths_disjoint", "paths_overlap"),
        )
    )
    assert d["failure_class"] == "needs_serialize"


def test_unknown_reason_code_fails_closed():
    d = classify_failure(
        _entry(
            _pass("base_main_current"),
            _pass("merge_tree_clean"),
            _chk("paths_disjoint", "brand_new_code"),
        )
    )
    assert d["failure_class"] == "env_config"
    assert "unknown_reason_code=brand_new_code" in d["evidence_hint"]


def test_empty_entry_returns_empty():
    d = classify_failure({})
    assert d["failure_class"] == ""
    assert d["retryable"] is False


def test_fallback_to_failure_reasons_without_preflight():
    d = classify_failure({"failure_reasons": ["verify_required"]})
    assert d["primary_reason"] == "verify_required"
    assert d["failure_class"] == "verify_missing"


def test_bucket_map_covers_all_failure_classes():
    # R5-b 的前提：6 类全部有桶归属，否则计数不可能闭合。
    assert set(FAILURE_CLASSES) <= set(_QUEUE_BUCKETS)


# ---- R5 分诊视图 ----


def _write_queue(tmp_path, rows):
    p = tmp_path / "merge_queue.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


def test_collect_merge_queue_closure(tmp_path):
    _write_queue(
        tmp_path,
        [
            {
                "queue_id": "q1",
                "lane_id": "l1",
                "status": "failed",
                "last_preflight": {"checks": [_chk("base_main_current", "base_stale")]},
            },
            {
                "queue_id": "q2",
                "lane_id": "l2",
                "status": "failed",
                "last_preflight": {
                    "checks": [
                        _pass("base_main_current"),
                        _pass("merge_tree_clean"),
                        _pass("paths_disjoint"),
                        _chk("verify_covers_base", "verify_required"),
                    ]
                },
            },
            {
                "queue_id": "q3",
                "lane_id": "l3",
                "status": "failed",
                "last_preflight": {
                    "checks": [
                        _pass("base_main_current"),
                        _chk("merge_tree_clean", "merge_conflict"),
                    ]
                },
            },
            {"queue_id": "q4", "lane_id": "l4", "status": "merged"},
        ],
    )
    block, notes = _collect_merge_queue(str(tmp_path))
    mq = block["merge_queue"]
    assert mq["available"] is True
    assert mq["failed_total"] == 3
    assert mq["bucket_sum"] == 3
    assert mq["closure_ok"] is True
    assert mq["buckets"]["rebase"]["count"] == 1
    assert mq["buckets"]["verify"]["count"] == 1
    assert mq["buckets"]["human"]["count"] == 1
    assert notes == []


def test_collect_merge_queue_malformed_line_is_visible(tmp_path):
    p = tmp_path / "merge_queue.jsonl"
    p.write_text('{"queue_id":"q1","status":"failed"}\nnot-json\n', encoding="utf-8")
    block, notes = _collect_merge_queue(str(tmp_path))
    assert block["merge_queue"]["malformed_lines"] == 1
    assert any("不可解析" in n for n in notes)


def test_collect_merge_queue_missing_ledger(tmp_path):
    block, notes = _collect_merge_queue(str(tmp_path))
    assert block["merge_queue"]["available"] is False
    assert any("不存在" in n for n in notes)


def test_render_shows_queue_section(tmp_path):
    _write_queue(
        tmp_path,
        [
            {
                "queue_id": "q1",
                "lane_id": "l1",
                "status": "failed",
                "last_preflight": {"checks": [_chk("base_main_current", "base_stale")]},
            }
        ],
    )
    block, _ = _collect_merge_queue(str(tmp_path))
    text = render_coordination({**block, "degraded": []})
    assert "队列分诊" in text
    assert "该 rebase=1" in text
    assert "l1" in text


# ---- 证据透传（R1-b）----


def test_probe_failure_carries_rc_and_stderr(tmp_path):
    store = MergeQueueStore(str(tmp_path), repo_root=str(tmp_path), create=False)
    detail = store.probe_main_head_detail()
    assert detail["head"] == ""
    assert detail["rc"] != 0
    assert detail["stderr_tail"]
    chk = check_base_main_current({"base_main_sha": "a" * 40}, "", probe=detail)
    assert chk["evidence"]["rc"] == detail["rc"]
    assert chk["evidence"]["stderr_tail"] == detail["stderr_tail"]
