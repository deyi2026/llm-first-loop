---
title: 并发收益实验：争用指标 T_parallel/max(w) 在同一 T0 下恒等于 1，属退化指标
scenario: 设计「并行 vs 串行」加速比实验时，自造的争用系数指标退化为恒等式，导致实测数字看似有意义实则零信息
root_cause: ""
solution: 不要用 T_parallel/max(w_i) 作争用指标（共用 T0 时恒为 1）。争用改为跨臂同位置样本时长对比，或测进程内等待；判定边界必须跑前冻结，指标自身要先做退化检查（能否取到非 1 的值域）。
evidence: K=2 实测：T_serial=83.848s(after c2 END_TS 1793863219.848 - T0 1793863136.0)，T_parallel=62.768s(max END_TS 1793863301.261 - T0 1793863238.493)，S=1.336；c=T_parallel/max(w_i)=1.000000 由构造恒等验证（两式分子分母同源）；并行臂 sum/max=1.460。产物存 /tmp/lfl_ab/artifacts/ 4 文件。
tags: [measurement-design, ab-experiment, parallel-speedup, degenerate-metric, honest-reporting]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-05T15:22:26.869581+08:00"
updated_at: "2026-11-05T15:22:26.869581+08:00"
---

场景：用并发子会话测量「并行 vs 串行」的加速比，协议冻结为指标 c = T_parallel / max(w_i)。

## 步骤
1. 写死指标口径与判定边界（跑前冻结，跑后不改）。
2. 记录 T0（起跑时间）与各样本自报 END_TS，用 max(END_TS) - T0 得 T_parallel。
3. 串行臂 T_serial = 末样本 END_TS - 首 T0。
4. 计算 S = T_serial / T_parallel。

## 关键陷阱（本次实测撞到）
c = T_parallel / max(w_i) 在所有样本共用同一 T0 时**恒等于 1**：
  T_parallel ≡ max(END_TS_i) - T0 ≡ max(w_i)
所以实测回执 c=1.000000 是构造恒等，不是「无争用」的证据。看到 c≈1 不许解读成「子代理不互相拖慢」。

## 可用替代
争用必须跨臂比较同类样本时长（串行臂第 i 个 vs 并行臂第 i 个），且要控制任务同形状；
或直接测同一进程内的资源等待。单臂内部算不出争用。

## 验证结果
K=2 pilot 实测：T_serial=83.85s，T_parallel=62.77s，S=1.336；
S 接近并行臂自身 sum/max 上限 1.460（离理想 2.0 的差来自任务时长离散 28.9s vs 62.8s + max() 木桶效应）。

## 反例/边界
- 只对 K=2 成立，不得线性外推到 K=4/8。
- 若某样本被工具事故污染（如本次 p1 因路径泄漏多花 10 轮），其时长不可用于争用推断。
- 「模型自己按顺序写文件」不是并行；必须独立会话并发。