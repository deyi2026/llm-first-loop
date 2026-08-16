#!/usr/bin/env python3
"""新旧形态真实 LLM token 对照（EVO-20260816-bfb9f215 待办 2 · 评测纪律第 5 条）.

同一 E2E 任务 × 两种工具面（仅 playwright_test / 仅 playwright_exec）× N 次重复，
真实驱动 LLM 循环，从 LoopResult 取 tokens_in/out（M52 provider usage 实计量，非估算）。

前置: .env 配好真实 LLM 凭据 + 网关 Web 在线（8902）+ chromium。
用法: .venv/bin/python scripts/bench_playwright_token.py [--repeat 3]
产出: data/e2e/bench/token_report_<ts>.json + 控制台对照表
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

# 同一任务，两种表达（各自贴合工具面的自然用法，不人为偏袒）：
TASK = {
    # 旧形态：只能给场景描述，工具生成脚本+截图（无交互/断言）
    "old": "用 playwright_test 验证网关 Web 首页（http://localhost:8902/）能正常渲染：访问首页并截图确认。confirm=true 真实执行。",
    # 新形态：模型自己写脚本，一次调用打包 navigate+检查+读内容
    "new": "用 playwright_exec 验证网关 Web 首页（http://localhost:8902/）能正常渲染：goto 首页、确认标题非空、用 axtree_text 读取页面结构确认有内容。confirm=true 真实执行。",
}

HIDE_FOR_OLD = {"playwright_exec"}   # 旧形态跑时藏新工具
HIDE_FOR_NEW = {"playwright_test"}   # 新形态跑时藏旧工具


def _patch_hidden(hidden_extra: set[str]):
    """monkeypatch run_mode hidden 集（benchmark 内聚，不改全局配置）."""
    import llm_loop.factory as f

    orig = dict(f._RUN_MODE_HIDDEN_TOOLS)
    f._RUN_MODE_HIDDEN_TOOLS = {
        k: (v | hidden_extra if k == "standard" else v) for k, v in orig.items()
    }
    return orig


def _restore(orig):
    import llm_loop.factory as f

    f._RUN_MODE_HIDDEN_TOOLS = orig


def run_once(tmp: Path, variant: str, repeat: int) -> dict:
    import os

    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    data_dir = tmp / f"{variant}_{repeat}"
    data_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        llm_api_key=os.environ["LLM_API_KEY"],
        llm_base_url=os.environ.get("LLM_BASE_URL", ""),
        llm_model=os.environ.get("LLM_MODEL", ""),
        data_dir=str(data_dir), run_mode="standard",
        extract_enabled=False, docs_dir="",
    )
    engine = build_engine(settings)
    names = set(engine.registry._tools.keys())  # noqa: SLF001
    assert ("playwright_test" in names) == (variant == "old"), f"{variant} 工具面错配"
    assert ("playwright_exec" in names) == (variant == "new"), f"{variant} 工具面错配"

    t0 = time.time()
    r = engine.run_single(TASK[variant])
    return {
        "variant": variant, "repeat": repeat,
        "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
        "rounds": r.rounds, "tool_calls": len(r.tool_calls),
        "elapsed_s": round(time.time() - t0, 1),
        "answer_tail": (r.final_answer or "")[-150:],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--tmp", default="data/e2e/bench/tmp")
    args = ap.parse_args()

    tmp = Path(args.tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    results = []

    for variant, hidden in (("old", HIDE_FOR_OLD), ("new", HIDE_FOR_NEW)):
        orig = _patch_hidden(hidden)
        try:
            for i in range(args.repeat):
                print(f"[{variant} #{i+1}] ...", flush=True)
                results.append(run_once(tmp, variant, i + 1))
                rr = results[-1]
                print(f"  -> in={rr['tokens_in']} out={rr['tokens_out']} rounds={rr['rounds']} ({rr['elapsed_s']}s)", flush=True)
        finally:
            _restore(orig)

    def _avg(v: str, key: str) -> float:
        xs = [r[key] for r in results if r["variant"] == v]
        return round(sum(xs) / len(xs), 1) if xs else 0.0

    summary = {
        v: {"tokens_in_avg": _avg(v, "tokens_in"), "tokens_out_avg": _avg(v, "tokens_out"),
            "rounds_avg": _avg(v, "rounds"), "tool_calls_avg": _avg(v, "tool_calls")}
        for v in ("old", "new")
    }
    old_in, new_in = summary["old"]["tokens_in_avg"], summary["new"]["tokens_in_avg"]
    if old_in and new_in:
        summary["delta"] = {"tokens_in_change": f"{(new_in - old_in) / old_in:+.1%}"}

    report = {"ts": time.time(), "repeat": args.repeat, "summary": summary, "results": results}
    out = Path("data/e2e/bench")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"token_report_{int(time.time())}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("\n== 对照 ==", json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"-> {path}")


if __name__ == "__main__":
    main()
