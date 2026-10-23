"""2026-10-23 长跑批断点续跑回归测试（零 LLM 零网络）.

背景（真实缺陷）: scripts/run_eval.py 此前**只在全部样本跑完后**才写 report.json，
84 样本真实 LLM 跑批中途被 kill → evals/results/eval_v2_m31flash_20261023/ 为空，
零产出。修复: 逐样本 checkpoint 落盘 + --resume 复用。

覆盖:
- 每跑完一个样本即写入 checkpoint.jsonl（逐行 JSONL）
- --resume 复用已完成的 (scenario_id, sample_index)，不再调 LLM
- checkpoint 末行被截断（中断）时如实跳过该行，不静默丢弃已完成样本
- 不带 --resume 时忽略已有 checkpoint（不复用旧结果）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import run_eval  # noqa: E402  — scripts 层模块（sys.path 注入后导入）

_SCENARIOS = {
    "name": "ckpt-test",
    "version": "v0",
    "scenarios": [
        {
            "id": "sc_a",
            "name": "场景A",
            "verdict": "verdict_chain_complete",
            "prompt": "p",
            "samples": 2,
            "params": {},
        },
        {
            "id": "sc_b",
            "name": "场景B",
            "verdict": "verdict_chain_complete",
            "prompt": "p",
            "samples": 2,
            "params": {},
        },
    ],
}


def _fake_runner(calls: list):
    """返回假 runner：记录调用并给出固定 trace/answer."""

    def _run(prompt, workdir, key, setup=None, max_iterations=10):
        calls.append((prompt, len(calls)))
        return {
            "trace": [{"name": "read_file", "arguments": {}}],
            "answer": "答案",
            "model_used": "fake-model",
            "rounds": 1,
            "truncated": False,
            "tokens_in": 1,
            "tokens_out": 1,
        }

    return _run


def _detail(i: int, model: str = "old-model", verdict: bool = True) -> dict:
    return {
        "sample": i,
        "verdict": verdict,
        "trace": [],
        "answer_head": "旧",
        "model_used": model,
        "rounds": 1,
        "truncated": False,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def test_checkpoint_written_per_sample(tmp_path):
    """每跑完一个样本即落盘一行（中断只丢当前样本）."""
    ck = tmp_path / "checkpoint.jsonl"
    calls: list = []
    orig = run_eval.run_dry_sample
    run_eval.run_dry_sample = _fake_runner(calls)
    try:
        out = run_eval.evaluate(
            _SCENARIOS, dry=True, samples_override=2, workdir=tmp_path, checkpoint_path=ck
        )
    finally:
        run_eval.run_dry_sample = orig

    assert len(calls) == 4
    lines = [ln for ln in ck.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 4
    recs = [json.loads(ln) for ln in lines]
    assert [(r["scenario_id"], r["sample"]) for r in recs] == [
        ("sc_a", 1),
        ("sc_a", 2),
        ("sc_b", 1),
        ("sc_b", 2),
    ]
    assert all(r["detail"]["model_used"] == "fake-model" for r in recs)
    assert len(out["results"]) == 2


def test_resume_reuses_completed_samples(tmp_path):
    """--resume 复用已完成样本：不再调 LLM，未完成部分照跑."""
    ck = tmp_path / "checkpoint.jsonl"
    with ck.open("w", encoding="utf-8") as fh:
        for i in (1, 2):
            fh.write(
                json.dumps(
                    {"scenario_id": "sc_a", "sample": i, "detail": _detail(i)},
                    ensure_ascii=False,
                )
                + "\n"
            )

    calls: list = []
    orig = run_eval.run_dry_sample
    run_eval.run_dry_sample = _fake_runner(calls)
    try:
        out = run_eval.evaluate(
            _SCENARIOS,
            dry=True,
            samples_override=2,
            workdir=tmp_path,
            checkpoint_path=ck,
            resume=True,
        )
    finally:
        run_eval.run_dry_sample = orig

    # 只跑 sc_b 的 2 个样本（sc_a 直接复用）
    assert len(calls) == 2
    by_id = {r["id"]: r for r in out["results"]}
    assert by_id["sc_a"]["passed"] == 2
    assert all(s["model_used"] == "old-model" for s in by_id["sc_a"]["samples_detail"])
    assert by_id["sc_b"]["samples"] == 2


def test_resume_ignores_truncated_last_line(tmp_path):
    """checkpoint 末行被中断截断 → 如实跳过该行，其余样本仍可复用."""
    ck = tmp_path / "checkpoint.jsonl"
    good = json.dumps(
        {"scenario_id": "sc_a", "sample": 1, "detail": _detail(1)},
        ensure_ascii=False,
    )
    ck.write_text(good + "\n" + '{"scenario_id": "sc_a", "sampl', encoding="utf-8")

    done = run_eval._load_checkpoint(ck)
    assert len(done) == 1
    assert done[("sc_a", 1)]["model_used"] == "old-model"


def test_no_resume_ignores_existing_checkpoint(tmp_path):
    """不带 --resume 时不复用旧结果（避免误把旧样本当本次结果）."""
    ck = tmp_path / "checkpoint.jsonl"
    ck.write_text(
        json.dumps(
            {"scenario_id": "sc_a", "sample": 1, "detail": _detail(1)},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    calls: list = []
    orig = run_eval.run_dry_sample
    run_eval.run_dry_sample = _fake_runner(calls)
    try:
        out = run_eval.evaluate(
            _SCENARIOS, dry=True, samples_override=2, workdir=tmp_path, checkpoint_path=ck
        )
    finally:
        run_eval.run_dry_sample = orig

    assert len(calls) == 4
    by_id = {r["id"]: r for r in out["results"]}
    assert all(s["model_used"] == "fake-model" for s in by_id["sc_a"]["samples_detail"])
