"""阶段A前缀稳定性检查器单元测试（EVO-20260920-3fb8aa0a）."""

from __future__ import annotations

import copy

from llm_loop.core import prefix_stability as ps


def _msgs(*pairs):
    return [{"role": role, "content": content} for role, content in pairs]


def _round(sid, final_msgs, *, head_msgs=None, ws_msgs=None, compressed=False):
    ps.observe_checkpoint(sid, "prov", "head", head_msgs if head_msgs is not None else final_msgs)
    ps.observe_checkpoint(
        sid, "prov", "working_set", ws_msgs if ws_msgs is not None else final_msgs
    )
    ps.observe_checkpoint(sid, "prov", "final", final_msgs)
    return ps.finalize_round(sid, "prov", compressed=compressed)


def test_cold_baseline_then_stable_append():
    sid = "pfx-cold"
    base = _msgs(("user", "a"), ("assistant", "b"))
    report = _round(sid, base)
    assert report is not None and report.verdict == "cold_baseline"
    report2 = _round(sid, base + _msgs(("user", "c")))
    assert report2.verdict == "stable_append"
    assert report2.final_lcp_msgs == 2
    assert report2.prev_final_msgs == 2 and report2.curr_final_msgs == 3
    assert report2.final_cached_chars == 2  # "a" + "b"
    assert report2.attribution == ""


def test_head_rewrite_attributed_to_head():
    sid = "pfx-head"
    base = _msgs(("user", "a"), ("assistant", "b"), ("user", "c"))
    _round(sid, base)
    rewritten = _msgs(("user", "a"), ("assistant", "B-rewritten"), ("user", "c"))
    report = _round(sid, rewritten)
    assert report.verdict == "prefix_broken"
    assert report.final_lcp_msgs == 1
    assert report.attribution == "head"
    assert report.stage_lcp == {"head": 1, "working_set": 1, "final": 1}


def test_working_set_fold_attributed_to_working_set():
    sid = "pfx-ws"
    base = _msgs(("user", "a"), ("assistant", "b"), ("user", "c"))
    _round(sid, base)
    folded = _msgs(("user", "a"), ("assistant", "receipt"), ("user", "c"))
    report = _round(sid, folded, head_msgs=base, ws_msgs=folded)
    assert report.verdict == "prefix_broken"
    assert report.final_lcp_msgs == 1
    assert report.attribution == "working_set"
    assert report.stage_lcp["head"] == 3  # head 前缀稳定
    assert report.stage_lcp["working_set"] == 1


def test_tail_reorder_attributed_to_final():
    sid = "pfx-tail"
    base = _msgs(("system", "s"), ("user", "a"), ("assistant", "b"))
    _round(sid, base)
    moved = _msgs(("system", "s"), ("assistant", "b"), ("user", "a"))
    report = _round(sid, moved, head_msgs=base, ws_msgs=base)
    assert report.verdict == "prefix_broken"
    assert report.final_lcp_msgs == 1
    assert report.attribution == "final"


def test_compressed_round_verdict():
    sid = "pfx-comp"
    _round(sid, _msgs(("user", "a"), ("assistant", "b")))
    report = _round(sid, _msgs(("assistant", "b2")), compressed=True)
    assert report.verdict == "compressed"
    assert report.attribution == ""
    assert report.compressed_round is True


def test_fail_open_and_no_mutation():
    sid = "pfx-failopen"
    msgs = _msgs(("user", "a"))
    snapshot = copy.deepcopy(msgs)

    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("boom")

    # 异常元素 → 整个检查点静默跳过，不向外抛
    ps.observe_checkpoint(sid, "prov", "final", [Boom()])
    ps.observe_checkpoint(sid, "prov", "head", [Boom(), None, 123, *msgs])
    assert ps.finalize_round(sid, "prov") is None  # final 缺失 → 不对比
    # 干净轮次照常工作；原始消息列表零改动
    ps.observe_checkpoint(sid, "prov", "final", msgs)
    report = ps.finalize_round(sid, "prov")
    assert report is not None and report.verdict == "cold_baseline"
    assert msgs == snapshot
