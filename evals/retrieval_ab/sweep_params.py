#!/usr/bin/env python3
"""参数敏感性 sweep：semantic_top_k x threshold 对线上融合检索的影响。

动机（20260922 失败分析）：api 组 miss=8 分三层——
  阈值截断 5 条（sim 0.4269-0.4967 < 0.50）、top20 截断 3 条（rank 25/28/57）、
  模型上限（rank 455-944，参数救不回）。本 sweep 量化放宽前两层的收益/回归。
方法：monkeypatch run_fused_eval 模块常量后逐组调 main()，不复制生产代码；
  P0 基线组用于对照 fused-20260922-065805.json 检测语料漂移。
"""
import sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))
import run_fused_eval as rfe

CONFIGS = [
    ("p0-baseline-topk20-th050",  20, 0.50),
    ("p1-topk40-th050",           40, 0.50),
    ("p2-topk40-th045",           40, 0.45),
    ("p3-topk60-th042",           60, 0.42),
]

for name, topk, th in CONFIGS:
    rfe.SEMANTIC_TOP_K = topk
    rfe.THRESHOLD["api"] = th
    sys.argv = ["run_fused_eval.py", "--provider", "api"]
    print(f"\n########## {name} ##########")
    before = set(HERE.glob("fused-*.json"))
    rfe.main()
    time.sleep(1.1)  # 时间戳文件名防同秒碰撞
    new = set(HERE.glob("fused-*.json")) - before
    for f in new:
        f.rename(HERE / f"sweep-{name}.json")
        print("archived:", f.name, "->", f"sweep-{name}.json")
