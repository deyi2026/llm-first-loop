# 评估：schedule.wake 授权锚定——session 还是 goal（EVO-20261007-8057c39a 案3）

日期：2026-10-07 ｜ 状态：评估完成，结论=维持 session 锚定 + 降级 payload 桥接

## 现状（代码事实）

- 授权：`schedule(wake=true)` 需调用方持 ingress capability，`store.add(..., wake_grant=delegate_ingress(...))` 时 `_authority.issue` 记账；投递侧 `ScheduleWakeDelivery` 在本进程 `_grants` 持有，跨进程靠 `recover_wake_grant` 从私有 authority 恢复（scheduler.py recover_wake_grant：仅 `wake_started_at==0` 且 state==pending）。
- 锚定粒度：capability 一次性、绑定 `session_id`（entry.session_id 为投递前提，schedule_delivery.py）。
- 状态层已有 goal 关联字段（`goal_id`/`wake_goal_binding_state`），但**授权与投递不读 goal**。

## 证据

- 2026-10-07 双 sid：owner 会话进程结束后 grant 丢失且 authority 不可恢复 → 6 轮瞬态退避 ~30 分钟全部失败（今天已由案1 改为立即降级）。
- 失败的本质：授权与"某个具体运行进程"的生命周期耦合；goal 层虽知道任务还在，却无权唤醒任何会话。

## 选项

| 方案 | 内容 | 代价/风险 |
|---|---|---|
| A. 维持 session 锚定 + 降级 payload 桥接（**已实现**） | owner 死→立即降级为通知，payload 携带 sid/session/原因/原始调度规格，下一个活会话 re-issue | 需一次人工/模型介入；周期性提醒跨 owner 死亡会断一拍 |
| B. goal 级自动 retarget | wake 到点时找同 goal 下任意活会话投递，无则不降级继续等 | admission 层改造；capability 语义从"一次性"变"可再分配"；死会话的定时能力自动流入新会话=复活语义，授权边界扩大，需单独演进评审 |
| C. goal 级 + 允许拉起新 run | 最强自动化 | 同 B 且更强；与"AI 会话不自动自我唤醒"的既有安全边界冲突（schedule 工具契约明示 wake 不可递归） |

## 结论

1. **维持 A**：capability 一次性、锚 session 的安全性质（不可复活、不可转授权）是 wake 设计的核心边界，不该为可用性放松。
2. 桥接已落地：`wake_degraded_payload`（sid/session_id/reason/message/trigger_at/repeat_interval/max_count），re-issue 成本一次工具调用。
3. **升级触发器**：若降级+re-anchor 的实际摩擦再次发生 ≥3 次（exception_log 里 grant_lost_owner_dead 高频且伴随人工抱怨），再立 B 的演进建议；C 维持不做。

## 引用

- EVO-20261007-8057c39a（含当日 6×30min 证据链）
- experience:EXPERIENCE-20261007-schedule-wake-grant-lost-owner-dead-6-30
- tests/unit/test_schedule_wake_owner_dead_degrade.py（新语义回归）
