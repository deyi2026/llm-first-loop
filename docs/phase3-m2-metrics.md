# 阶段3 M2 生效时延度量（G2）：口径、实现与对照数据

> 交付物：`HumanTurnQueue.aggregate_interject_metrics`（只读聚合，ms）+
> `GET /api/v1/chat/queue/metrics?session_id=`（零写副作用暴露端点）+
> 测试 `tests/web/test_phase3_m2_metrics.py`（3 用例：口径数学/端到端/对照采集）。
> 原始数据：`reports/phase3/m2/metrics.json`（2026-10-13 02:0x，M1+M2 代码）。

## 1. 三口径定义（Phase3 §7.1；全部由持久化时间戳机械推导，无墙钟注入）

| 口径 | 定义 | 数据源字段 |
|---|---|---|
| t_ack | 入队→HTTP 受理 | interject_requested_at − created_at |
| t_persist | 受理→进入会话历史（含轮边界等待与 session 写盘，即「回执≠生效」差值本体） | received_at − interject_requested_at |
| t_effect | 入队→生效端到端 | received_at − created_at |
| t_applied | 入队→首个动作（工具派发/终答出口/CBF 网关） | applied_at − created_at（未 applied 为 null） |

百分位：最近邻序法 P50/P95；仅统计 `interject_received*` 终态项，denied/requeued 不混入（口径含混即失真）；n=0 → null（不造数）。

## 2. 对照数据

**M0 基线（01:32，pre-M1，S01 单样本，工具 2.5s）**

| n | t_ack | t_persist | t_effect |
|---|---|---|---|
| 1 | 2.3 ms | 2490.6 ms | 2492.9 ms |

**M1+M2（02:0x，3 次独立 run，各一次长工具中插话，工具 2.0s）**

| n | P50 t_ack | P50 t_persist | P50 t_effect | P50 t_applied |
|---|---|---|---|---|
| 3 | 1.9 ms | 1994.7 ms | 1996.6 ms | 1998.8 ms |

P95：t_ack 2.0ms / t_persist 1999.9ms / t_effect 2001.9ms / t_applied 2004.1ms（完整见 metrics.json）。

## 3. 观察（机械事实，不做过度解读）

1. **t_ack 毫秒级且稳定**（1.8–2.3ms）：受理路径轻。
2. **t_effect 由轮边界等待主导**：长工具在途时，受理→生效的差值≈工具剩余时长（基线 2.5s 工具 → ~2490ms；本表 2.0s 工具 → ~1995ms）。这是「回执≠生效」的量化本体，与 M0 报告 S01 结论一致。
3. **t_applied ≈ t_effect + 2ms**：首个动作紧跟消费点（同轮派发），分级与度量口径自洽。
4. 工具空窗期插话的 t_effect 预期接近 t_ack（轮边界即时到达）——本表未覆盖该形态，留作 M3/M4 验收场景补充（不构成缺口，机制上同一消费点）。

## 4. 实现说明与设计书偏差记录

- 设计书 §4.2 原草图把聚合放 `run_finalizer.py`；实测装配下 run_finalizer（engine 侧）拿不到 Web 队列实例（hq 按 data_dir 挂在 app.state），跨层注入违背「M2 不动主链路」。聚合落在数据的所有者 `HumanTurnQueue`（同文件同锁语义），暴露走 routes 只读端点——意图（聚合+暴露）不变，接缝按实测事实修正并在此留痕。
- 时间戳零新增：三口径完全复用 M0 已核字段 + M1 的 applied_at/cbf_at；无埋点侵入主链路。
