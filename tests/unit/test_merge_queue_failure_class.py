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


# ---- 终态 lane 不得被给可执行命令（真实账本跑出来的缺陷回归）----
#
# 实测 data/audit/merge_queue.jsonl 时发现：10 项 verify 类失败对应的 lane 全部
# 已 merged/abandoned，而视图仍给出 `lane_merge_request(...)`——那是一条必然失败的
# 命令。R5-c 要求「可直接粘贴」，给一条注定报错的命令比不给更糟。


def test_terminal_lane_gets_no_executable_command(tmp_path):
    _write_queue(
        tmp_path,
        [
            {
                "queue_id": "q-done",
                "lane_id": "l-done",
                "status": "failed",
                "last_preflight": {
                    "checks": [_chk("verify_covers_base", "verify_required")]
                },
            }
        ],
    )
    (tmp_path / "lanes.jsonl").write_text(
        '{"lane_id":"l-done","status":"merged"}\n', encoding="utf-8"
    )
    block, _ = _collect_merge_queue(str(tmp_path))
    mq = block["merge_queue"]
    assert mq["terminal_total"] == 1
    item = mq["buckets"]["verify"]["items"][0]
    assert item["terminal"] is True
    assert item["lane_status"] == "merged"
    assert not item["next_command"].startswith("lane_merge_request")
    assert "历史项" in item["next_command"]


def test_non_terminal_lane_keeps_executable_command(tmp_path):
    """修缺陷不能把正常路径一起关掉：在途 lane 仍须拿到可执行命令。"""
    _write_queue(
        tmp_path,
        [
            {
                "queue_id": "q-live",
                "lane_id": "l-live",
                "status": "failed",
                "last_preflight": {
                    "checks": [_chk("verify_covers_base", "verify_required")]
                },
            }
        ],
    )
    (tmp_path / "lanes.jsonl").write_text(
        '{"lane_id":"l-live","status":"verifying"}\n', encoding="utf-8"
    )
    block, _ = _collect_merge_queue(str(tmp_path))
    item = block["merge_queue"]["buckets"]["verify"]["items"][0]
    assert item["terminal"] is False
    assert item["next_command"].startswith('lane_merge_request(lane_id="l-live")')


def test_render_surfaces_terminal_count(tmp_path):
    _write_queue(
        tmp_path,
        [
            {
                "queue_id": "q-done",
                "lane_id": "l-done",
                "status": "failed",
                "last_preflight": {"checks": [_chk("base_main_current", "base_stale")]},
            }
        ],
    )
    (tmp_path / "lanes.jsonl").write_text(
        '{"lane_id":"l-done","status":"abandoned"}\n', encoding="utf-8"
    )
    block, _ = _collect_merge_queue(str(tmp_path))
    text = render_coordination({**block, "degraded": []})
    assert "历史=1" in text
    assert "历史项" in text


# ---- M1 队列降噪双轨（DESIGN-20261116 §2，追加段：只加不改）----
#
# 双轨纪律：上方既有断言零修改继续通过=legacy 轨回归；本段只测新增 actionable/来源
# 完整性轨与 BUG-10（v1.3 勘误）安全降级——不为兼容保留不安全建议。


def _write_lanes(tmp_path, rows):
    p = tmp_path / "lanes.jsonl"
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return p


#: BUG-10 负测口径：next_command 不得出现的写命令特征（requeue/rebase/merge 三族）。
_WRITE_CMD_TOKENS = ("lane_queue_submit", "lane_merge_request", "rebase", "git -C")


def _all_items(mq):
    return [it for b in mq["buckets"].values() for it in b["items"]]


def _mixed_fixture(tmp_path):
    # 健康源三分夹具：l-live 在途（actionable）/l-done 终态/l-ghost 不在账（unknown）
    _write_queue(
        tmp_path,
        [
            {
                "queue_id": "q1",
                "lane_id": "l-live",
                "status": "failed",
                "last_preflight": {"checks": [_chk("base_main_current", "base_stale")]},
            },
            {
                "queue_id": "q2",
                "lane_id": "l-done",
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
                "lane_id": "l-ghost",
                "status": "failed",
                "last_preflight": {
                    "checks": [
                        _pass("base_main_current"),
                        _chk("merge_tree_clean", "merge_conflict", {"conflicting_paths": ["a.py"]}),
                    ]
                },
            },
        ],
    )
    _write_lanes(
        tmp_path,
        [
            {"lane_id": "l-live", "status": "active"},
            {"lane_id": "l-done", "status": "merged"},
        ],
    )


def test_dual_track_three_way_split_and_actionable_identity(tmp_path):
    _mixed_fixture(tmp_path)
    block, notes = _collect_merge_queue(str(tmp_path))
    mq = block["merge_queue"]
    # legacy 轨原口径逐字段不动
    assert mq["failed_total"] == 3
    assert mq["bucket_sum"] == 3
    assert mq["closure_ok"] is True
    assert mq["terminal_total"] == 1
    assert mq["buckets"]["rebase"]["count"] == 1
    assert mq["buckets"]["verify"]["count"] == 1
    assert mq["buckets"]["human"]["count"] == 1
    assert notes == []
    # 新增轨：三分计数 + 恒等式（只作用 actionable 轨）
    assert mq["actionable_total"] == 1
    assert mq["unknown_total"] == 1
    assert mq["actionable_bucket_sum"] == 1
    assert mq["actionable_buckets"]["rebase"]["count"] == 1
    assert mq["actionable_bucket_sum"] == (
        mq["failed_total"] - mq["terminal_total"] - mq["unknown_total"]
    )
    # 已 merged lane 不得进入 actionable 轨（不再收到 merge_request 建议）
    assert all(
        it["lane_id"] != "l-done" for b in mq["actionable_buckets"].values() for it in b["items"]
    )
    assert mq["source_complete"] is True
    assert mq["parsed_closure_ok"] is True
    assert mq["overall_view_ok"] is True
    assert mq["safe_to_execute"] is True
    # BUG-10: unknown 项即使整体可信也不发写命令；actionable 项保留可执行建议
    items = {it["lane_id"]: it for it in _all_items(mq)}
    assert items["l-live"]["classification"] == "actionable"
    assert items["l-live"]["next_command"].startswith("git -C")
    assert items["l-done"]["classification"] == "terminal"
    assert items["l-ghost"]["classification"] == "unknown"
    assert not any(tok in items["l-ghost"]["next_command"] for tok in _WRITE_CMD_TOKENS)
    assert "人工核对" in items["l-ghost"]["next_command"]
    assert mq["actionable_next_command"] == [items["l-live"]["next_command"]]


def test_missing_lanes_ledger_degrades_every_command(tmp_path):
    # BUG-10 负测：lanes 账本缺失 → 全量 unknown、无任何写命令、safe_to_execute=false
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
                "last_preflight": {"checks": [_chk("verify_covers_base", "verify_required")]},
            },
        ],
    )
    block, notes = _collect_merge_queue(str(tmp_path))
    mq = block["merge_queue"]
    assert mq["source_complete"] is False
    assert mq["lane_health"]["read_ok"] is False
    assert mq["unknown_total"] == 2
    assert mq["actionable_total"] == 0
    # parsed closure ≠ source completeness：可解析部分自洽但来源不完整
    assert mq["parsed_closure_ok"] is True
    assert mq["overall_view_ok"] is False
    assert mq["safe_to_execute"] is False
    assert mq["actionable_next_command"] == []
    for it in _all_items(mq):
        assert it["classification"] == "unknown"
        assert not any(tok in it["next_command"] for tok in _WRITE_CMD_TOKENS)
        assert "人工核对" in it["next_command"]
    # legacy notes 行为不变（降级披露由渲染层负责，不靠塞 note）
    assert notes == []


def test_mq_bad_rows_break_source_complete_and_degrade(tmp_path):
    _write_queue(
        tmp_path,
        [
            {
                "queue_id": "q1",
                "lane_id": "l-live",
                "status": "failed",
                "last_preflight": {"checks": [_chk("base_main_current", "base_stale")]},
            }
        ],
    )
    _write_lanes(tmp_path, [{"lane_id": "l-live", "status": "active"}])
    p = tmp_path / "merge_queue.jsonl"
    p.write_text(p.read_text(encoding="utf-8") + "not-json\n", encoding="utf-8")
    block, notes = _collect_merge_queue(str(tmp_path))
    mq = block["merge_queue"]
    assert mq["malformed_lines"] == 1  # legacy 字段照旧
    assert mq["mq_bad_rows"] == 1
    assert mq["source_complete"] is False
    assert mq["overall_view_ok"] is False
    assert mq["safe_to_execute"] is False
    assert mq["actionable_next_command"] == []
    for it in _all_items(mq):
        assert not any(tok in it["next_command"] for tok in _WRITE_CMD_TOKENS)
    assert any("不可解析" in n for n in notes)  # legacy note 照旧


def test_duplicate_conflicting_lane_status_is_unknown_and_not_safe(tmp_path):
    _write_queue(
        tmp_path,
        [
            {
                "queue_id": "q1",
                "lane_id": "l-dup",
                "status": "failed",
                "last_preflight": {"checks": [_chk("verify_covers_base", "verify_required")]},
            }
        ],
    )
    _write_lanes(
        tmp_path,
        [
            {"lane_id": "l-dup", "status": "active"},
            {"lane_id": "l-dup", "status": "merged"},
        ],
    )
    block, _ = _collect_merge_queue(str(tmp_path))
    mq = block["merge_queue"]
    assert mq["lane_health"]["duplicate_lane_ids"] == 1
    assert "l-dup" in mq["lane_health"]["conflict_lane_ids"]
    assert mq["source_complete"] is False
    # 冲突 lane → 保守 unknown（宁可 unknown 不冒充已知）
    assert mq["unknown_total"] == 1
    assert mq["actionable_total"] == 0
    # legacy last-wins 不动：末行 merged → terminal_total 仍为 1
    assert mq["terminal_total"] == 1
    # 该项同时落 legacy-terminal 与 unknown → 恰属三者之一被破坏，parsed_closure_ok=false
    assert mq["parsed_closure_ok"] is False
    assert mq["overall_view_ok"] is False
    assert mq["safe_to_execute"] is False
    for it in _all_items(mq):
        assert not any(tok in it["next_command"] for tok in _WRITE_CMD_TOKENS)


def test_invalid_lane_status_counts_and_degrades(tmp_path):
    _write_queue(
        tmp_path,
        [
            {
                "queue_id": "q1",
                "lane_id": "l-zombie",
                "status": "failed",
                "last_preflight": {"checks": [_chk("verify_covers_base", "verify_required")]},
            }
        ],
    )
    _write_lanes(tmp_path, [{"lane_id": "l-zombie", "status": "zombie-mode"}])
    block, _ = _collect_merge_queue(str(tmp_path))
    mq = block["merge_queue"]
    assert mq["lane_health"]["invalid_status_rows"] == 1
    assert mq["source_complete"] is False
    assert mq["unknown_total"] == 1
    assert mq["actionable_total"] == 0
    item = _all_items(mq)[0]
    assert item["terminal"] is False  # legacy: 无效 status 不算终态
    assert item["classification"] == "unknown"
    assert not any(tok in item["next_command"] for tok in _WRITE_CMD_TOKENS)


def test_lanes_bad_rows_make_every_item_conservatively_unknown(tmp_path):
    # 坏行不静默丢：lanes 有坏行时无法排除「某 lane 最新行已损坏」→ 全量保守 unknown
    _write_queue(
        tmp_path,
        [
            {
                "queue_id": "q1",
                "lane_id": "l-live",
                "status": "failed",
                "last_preflight": {"checks": [_chk("base_main_current", "base_stale")]},
            }
        ],
    )
    (tmp_path / "lanes.jsonl").write_text(
        "{\"lane_id\":\"l-live\",\"status\":\"active\"}\nnot-json\n", encoding="utf-8"
    )
    block, _ = _collect_merge_queue(str(tmp_path))
    mq = block["merge_queue"]
    assert mq["lane_health"]["read_ok"] is True
    assert mq["lane_health"]["bad_rows"] == 1
    assert mq["source_complete"] is False
    assert mq["unknown_total"] == 1
    assert mq["actionable_total"] == 0
    assert mq["parsed_closure_ok"] is True  # 0 == 1 - 0 - 1
    assert mq["safe_to_execute"] is False
    assert mq["actionable_next_command"] == []
    for it in _all_items(mq):
        assert it["classification"] == "unknown"
        assert not any(tok in it["next_command"] for tok in _WRITE_CMD_TOKENS)


def test_unreadable_lanes_ledger_same_degradation_as_missing(tmp_path):
    (tmp_path / "lanes.jsonl").mkdir()  # open() → IsADirectoryError（OSError 族）
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
    mq = block["merge_queue"]
    assert mq["lane_health"]["read_ok"] is False
    assert mq["source_complete"] is False
    assert mq["unknown_total"] == 1
    assert mq["safe_to_execute"] is False
    for it in _all_items(mq):
        assert not any(tok in it["next_command"] for tok in _WRITE_CMD_TOKENS)


def test_render_three_way_split_line_precedes_legacy_bucket_line(tmp_path):
    _mixed_fixture(tmp_path)
    block, _ = _collect_merge_queue(str(tmp_path))
    text = render_coordination({**block, "degraded": []})
    lines = text.split("\n")
    idx3 = next(i for i, ln in enumerate(lines) if "当前待办=" in ln)
    idx_legacy = next(i for i, ln in enumerate(lines) if "该 rebase=1" in ln)
    assert idx3 < idx_legacy  # 三分行置前
    assert "failed=3" in lines[idx3]
    assert "当前待办=1" in lines[idx3]
    assert "历史=1" in lines[idx3]
    assert "来源未知=1" in lines[idx3]
    assert "坏行=0" in lines[idx3]
    assert "best-effort" in lines[idx3]
    # legacy 四桶行与 closure_ok 行保留在后
    assert "闭合=ok(3)" in text
    assert "历史=1" in lines[idx_legacy]
    assert "该 rebase=1" in text


def test_render_annotates_degraded_view_when_source_incomplete(tmp_path):
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
    )  # 无 lanes.jsonl
    block, _ = _collect_merge_queue(str(tmp_path))
    text = render_coordination({**block, "degraded": []})
    assert "来源未知=1" in text
    assert "视图降级" in text
