# Phase4 M0 基线对照报告（现状代码，零核心变更）

- 场景定义：`docs/phase4-effect-latency-design.md` §6 M0；脚本：`tests/phase4/test_m0_scenarios.py`
- 口径：t_effect = received_at − created_at（hq 条目时间戳，与 aggregate_interject_metrics 同源）；P50/P95 最近邻序法
- 运行：`python3 -m pytest tests/phase4/test_m0_scenarios.py -q`（4 passed, 38.6s，2026-10-13）

## 基线数据（现状锚点）

| 场景 | 构造 | n | t_effect P50 | t_effect P95 | 判读 |
|---|---|---|---|---|---|
| S13 在途打断基线 | `sleep 2.0` + 0.3s 注入 | 5 | **1681.8 ms** | 1688.0 ms | ≈2.0−0.3s ✓ 与设计锚点（≈1.7s）吻合；插话滞留 mailbox 至工具自然完成，轮转轮首消费 |
| S14 不可中断保守 | revocable=False 工具（phase4_locked_sleep）+ 0.3s 注入 | 5 | **1670.5 ms** | 1706.7 ms | 自然边界（与 S13 同——现状无打断机制）；M2 后此场景必须保持此行为 |
| S15 竞速如实 | `sleep 1.5` + 1.45s 注入（剩余 ~50ms） | 6 | 32.3 ms | 37.5 ms | 6/6 natural_first(noise_band)：received−tool_done ∈ [−37.7, −18.5] ms（观察噪声带内=自然边界消费；M0 构造上无 interrupt_first 可能）。M2 后改用事件序真值判定 |
| S16 空窗插话 | 第二次 LLM 调用生成窗口 1.5s + 窗口开启后 50ms 注入 | 5 | **1413.6 ms** | 1438.4 ms | ≈生成窗口剩余 ✓；现状=终答结算边界消费（CBF）；M1 目标：序列间隙直接收割 P50≤50ms |

t_ack（HTTP 受理）：S13/S14/S15 均 <2ms；S16 ≈1.6ms —— 与 Phase3 度量一致，受理无瓶颈，差值本体在生效侧。

## 结论

1. 差值本体确认：在途工具/生成窗口的剩余时长 ≈ t_effect（S13: 1.68s vs 剩余 1.7s；S16: 1.41s vs 窗口剩余 ~1.45s）。
2. M1 目标场景（S16 序列间隙）：现状 P50=1413.6ms → 目标 ≤50ms。
3. M2 目标场景（S13）：现状 P50=1681.8ms → 目标 ≤500ms。
4. S14 保守等待基线已锚定（1.67s），M2 后不得劣化该行为语义。
5. S15 竞速窗口构造验证通过（注入-完成边界 50ms 级），分支判定 M2 起用事件序真值。
