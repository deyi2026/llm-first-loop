# 多段层 fork 继承归属裁决 — Mini-Design v1

Date: 2026-10-02
Status: **IMPLEMENTED（2026-10-02，与 P0-3 收口同批：脚本守卫扩展 + 单测 6/6 + ruff/pyright 干净 + 真实数据 marked 47 / replicas_skipped 1 / 累计 55 / 幂等 0 新增，结果与 §6 预期逐项一致）**
上游：`docs/DESIGN-20261002-p0-3-strict-durability-decision.md` §7（悬置的多段层归属裁决）
授权：用户 2026-10-02 09:50「按建议执行」（建议 = 1,189 个重复 attempt_id 的复制根因排查，mini-design 级别）

---

## 1. 根因结论

多段 session 目录层观察到的跨 session attempt_id 逐字段重复（同微秒 ts、同 call_id、
payload 完全一致）**不是日志损坏，也不是双写竞态**，而是 `session-fork` 的设计内行为：

- 机制：`src/llm_loop/event_log/fork.py` L181-184 —— fork 物理复制继承事件，
  **保留 `type`/`ts`/`payload`，仅重分配 `seq`/`event_id`/`session_id`**；
- 子会话布局（实测 e89b29b3）：`seq=1 session.created` → `seq=2..N+1` 副本前缀
  （N = `inherited_event_count`）→ `seq=N+2 session.forked` marker；
  即 **marker 落在副本前缀之后**，副本的机械边界 = `event.seq < forked_marker.seq`；
- 大历史 fork（如 28,701 条）导致子会话超滚动阈值 → 双方都成多段目录，
  这解释了为什么重复集中在多段层。

## 2. 证据链（2026-10-02 全量扫描，30,280 个唯一 attempt）

| 事实 | 数值 |
|---|---|
| 跨 session 重复的 attempt_id | 1,203（决策时点 1,189，同源） |
| `32d694c9 ↔ e89b29b3`（09-20 fork，继承 28,701 事件） | **1,189** |
| `001dc093 ↔ b8938fdb`（09-23 fork，继承 287 事件） | 12 |
| `2e92b709 ↔ 4ebe537c` | 2 |
| 无谱系关联（无解释）的重复 | **0** |
| 复制语义抽验 | ts/payload 逐字段一致；seq/event_id/session_id 已重分配 ✓ |

对账：决策 §7 的「1,189」精确等于最大 fork 对——测量口径确认，无未解释残差。

## 3. 48 个多段层 opened-without-settled 的再定性

原假设「复制/归属 artifact」**被证伪**：

1. 48 个 attempt 的 settled 在**所有** session（含全部谱系）中都不存在——
   fork 截断假设要求 settled 至少存在于父会话，不成立；
2. 仅 1/48 落在 fork 子会话，且位于副本前缀内（e89b29b3 seq=18958，
   其原件在父 32d694c9 同 seq——该 attempt 本身 settle 丢失）；
3. 其余 47 个为原生（非副本）出现：glm 46 + cognilocal 1；
4. 形态：attempt 之后同 session 均有后续事件（next 类型含
   `llm.partial_checkpoint` 18 / `provider.call.opened` 16 / `message.appended` 12 等）
   —— 非崩溃形态；
5. 时间分布：09-11~09-22 稀疏散布（该窗口 glm settle 覆盖率 ~99.8%，
   非系统性覆盖缺口），**09-23 起为 0**。

定性：**历史 settle-loss**（fail-open settle 的静默丢弃路径：
`transport_attempt` open 异常时 `yield None; return` 不经 settle；
settle 异常被 `suppress(Exception)` 吞掉）。逐例微观路径已无痕迹可考
（异常被抑制、未落日志），但终态语义唯一：opened 无 settled、结果未知。

## 4. 归属裁决（本设计冻结）

1. **去重键**：`attempt_id` 是 attempt 的全局唯一标识；任何消费者按 attempt_id
   全局唯一化后不得因 fork 副本重复计数。
2. **副本定义**：session 内存在 `session.forked` marker 且 `seq < marker.seq` 的
   事件出现为副本；**权威出现** = 原生（非副本）出现。
3. **settle-anywhere 守卫**：任一 session（含副本）存在同 attempt_id 的
   `provider.transport.settled` → 该 attempt 永不算 orphan。
4. **标记规则**：仅对「settle 全局不存在 + 原生出现」的 attempt 追加
   `provider.transport.orphaned`（机械事实 `opened_without_settled`，
   不含 outcome/reason——维持决策 §5 语义）；副本永不标记。

### 4.1 对既有单文件层的影响

settle-anywhere 守卫使标记只会更保守（不会新标记任何 attempt）。实测单文件层
8 个已标记 orphans 的 attempt 均无全局 settle，默认口径结果不变。

## 5. 对 R1 类历史重放的影响

- R1 冻结 cohort（120 sessions）当时只消费单文件层，不受影响；
- 未来任何扩展到多段层的重放/审计**必须**先做 fork 去重：
  按 attempt_id（transport 事件）或按「子会话 seq < forked marker 的前缀丢弃」
  （通用事件），否则会把继承副本重复计入重复调用/观测统计。

## 6. 实施

`scripts/evidence/mark_orphaned_transport_attempts.py`：

1. 两阶段：先全量建「全局 settled / orphaned / fork-marker seq」索引
   （覆盖单文件 + 多段，与扫描范围无关——settle-anywhere 是更强事实）；
2. `--include-multi-segment` 生效：多段目录纳入扫描；
3. 副本（seq < fork marker.seq）跳过并计数 `replicas_skipped`；
4. 幂等保持（全局 orphaned 索引短路）。

真实数据预期：marked = 47（glm 46 + cognilocal 1，原生），replicas_skipped = 1，
already_orphaned = 8（单文件层既有）；重跑 0 新增。

## 7. 验收

1. 单测：fork 副本不标记 + 原生标记；settle-anywhere 守卫；幂等；
   默认口径（不含多段）行为不变；
2. 真实数据：运行结果与 §6 预期逐项一致；重跑 0 新增；
3. focused gate + 全量回归。
