"""usage-missing ≠ 0 回归（2026-09-12，GPT 复审第 1/5 点）。

背景：lfl store 的 tool-call assistant turn usage 未持久化（记 0），仅末 turn
记 run 级汇总。旧实现 sum(or 0) 把假 0 当观测值，美化 token efficiency。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from telemetry import extract_raw, score_fcr


def _ev(turns, calls=None):
    return {"source": "t", "t0": 1.0, "turns": turns,
            "calls": calls if calls is not None else
            [{"round": 1, "turn": 1, "name": "read_file", "args": "x",
              "classes": ["read"], "ok": True, "end_rel": 2.0}]}


def test_R1_lfl_fake_zero_front_runs():
    """GPT-回归1：前几轮 usage=0、末轮汇总 → to-first 两字段 None，
    run-level input/cache/output 不变（取末 turn 汇总值）。"""
    turns = [{"tokens_in": 0, "cached": 0, "tokens_out": 0} for _ in range(3)] + \
            [{"tokens_in": 33451, "cached": 32886, "tokens_out": 346}]  # 真实 t01 形态
    f = extract_raw(_ev(turns))
    assert f["tokens_to_first_mechanical_valid_action"] is None
    assert f["cache_hit_tokens_to_first_mechanical_valid"] is None
    assert f["input_tokens"] == 33451
    assert f["cache_hit_tokens"] == 32886
    assert f["new_prefill_tokens"] == 565
    assert f["output_tokens"] == 346


def test_R2_real_per_turn_usage():
    """GPT-回归2：真实 per-turn usage → 正常非零 token/cache 数。"""
    turns = [{"tokens_in": 5000, "cached": 4000, "tokens_out": 50},
             {"tokens_in": 8000, "cached": 7000, "tokens_out": 60}]
    f = extract_raw(_ev(turns))            # 首有效调用在 turn 1 → 只含 turn0
    assert f["tokens_to_first_mechanical_valid_action"] == 5000
    assert f["cache_hit_tokens_to_first_mechanical_valid"] == 4000
    assert f["input_tokens"] == 13000
    assert f["output_tokens"] == 110


def test_R3_tnv_zero_enters_branch():
    """GPT-回归3：tnv=0 仍进入计算分支，不被 truthiness 吃掉 → 空→None，不 crash。"""
    turns = [{"tokens_in": 5000, "cached": 4000, "tokens_out": 50}]
    calls = [{"round": 1, "turn": 0, "name": "read_file", "args": "x",
              "classes": ["read"], "ok": True, "end_rel": 1.5}]
    f = extract_raw(_ev(turns, calls))
    assert f["tokens_to_first_mechanical_valid_action"] is None
    assert f["cache_hit_tokens_to_first_mechanical_valid"] is None
    assert f["first_mechanical_valid_round"] == 0
    s = score_fcr(f, _ev(turns, calls), {"first_tools": ["read"]})
    assert s["tokens_to_first_task_valid_action"] is None


def test_R4_no_observable_usage_anywhere():
    """GPT-规则3：全 run 无任何可观测 usage → run-level 也 None，不得记 0。"""
    turns = [{"tokens_in": 0, "cached": 0, "tokens_out": 0}] * 2
    f = extract_raw(_ev(turns))
    for k in ("input_tokens", "output_tokens", "cache_hit_tokens",
              "new_prefill_tokens", "tokens_to_first_mechanical_valid_action",
              "cache_hit_tokens_to_first_mechanical_valid"):
        assert f[k] is None, k


def test_R5_scorer_consistent_with_raw():
    """scorer 的 tokens_to_first_task_valid_action 与 raw 同规则（R1 形态 → None）。"""
    turns = [{"tokens_in": 0, "cached": 0, "tokens_out": 0}] * 2 + \
            [{"tokens_in": 9000, "cached": 8000, "tokens_out": 100}]
    ev = _ev(turns)
    f = extract_raw(ev)
    s = score_fcr(f, ev, {"first_tools": ["read"]})   # raw 需含 ok_signal 才进配对分支
    assert s["tokens_to_first_task_valid_action"] is None
    assert s["first_tool_selection_correct"] is True
    assert s["first_call_ready"] is True


def test_R6_json_null_roundtrip():
    """JSON 落盘保持 null，不得序列化成 0。"""
    import json
    turns = [{"tokens_in": 0, "cached": 0, "tokens_out": 0}]
    raw = json.dumps(extract_raw(_ev(turns)))
    assert '"tokens_to_first_mechanical_valid_action": null' in raw
    assert '"cache_hit_tokens_to_first_mechanical_valid": null' in raw


if __name__ == "__main__":
    import traceback
    ok = 0
    for name, fn in sorted({k: v for k, v in globals().items()
                            if k.startswith("test_")}.items()):
        try:
            fn(); print(f"PASS {name}"); ok += 1
        except AssertionError:
            print(f"FAIL {name}"); traceback.print_exc()
    print(f"{ok}/6")
    sys.exit(0 if ok == 6 else 1)
