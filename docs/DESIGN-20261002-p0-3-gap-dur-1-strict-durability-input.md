# GAP-DUR-1 Strict Durability — P0-3 裁决输入（无代码）

Date: 2026-10-02
Status: **DECISION INPUT — 供 P0-3 显式裁决；本文不改代码**
上游：`docs/DESIGN-20261002-p0-2-provider-settlement-coverage-plan.md` §2 GAP-DUR-1（"现状 fail-open shadow 不可默认继承为 v1.1 RI-1 承诺"）
权威：`docs/DESIGN-20260930-model-invocation-history-replay-safety.md` v1.1 RI-1 承诺文本。

## 1. 现状事实（代码/审计为证）

1. **fail-open shadow**：`ProviderCallSettlementJournal` 契约原文"never blocks or retries provider work"（`provider_settlement.py` L162）；settlement 异常不改变 transport 行为。所有 seam（API×4 + Web×2）的 prepared/settled/hmac 构造均包在 `except Exception: 诚实省略/None` 内。
2. **事件落盘**：经 EventStore → `data/event_logs/*.jsonl`（per-session）；audit §5 同型查询可复现统计。
3. **崩溃窗口**：`transport_attempt()` 在物理发送前 open、`finally` settle。进程在窗口内死亡（kill -9 / 断电 / 容器 OOM）→ 该 session 日志留下 `provider.transport.opened` 无对应 `settled`。B2 的 prepared 字段 write-before-send 已具备（audit D3），故崩溃不丢 prepared，只悬置 outcome。
4. **attempt_id 语义**：每次 transport attempt 新生成 id；同 id 二次 settle 会 raise `conflicting provider transport settlement`（L533）。孤儿 attempt 不阻塞后续新 attempt（id 不复用）。

## 2. 待 P0-3 显式裁决的问题

### Q1 孤儿 reconciliation
- **建议**（承 plan §2）：启动扫描悬挂 pattempt，标记 `orphaned`，**不回填 outcome**（程序不伪造结局；unknown 保持 unknown）。
- 待裁决：扫描范围（仅最近崩溃 session vs 全历史一次性）；标记形态（新增 `provider.transport.orphaned` 事件 vs 启动期一次性扫描报告进 audit）；扫描时机（进程启动 vs 显式脚本）。

### Q2 RI-1 是否继承 fail-open
- v1.1 RI-1 若承诺 strict durability（观测事实不因进程死亡而永久悬置），则需：崩溃后恢复路径 + orphaned 标记（Q1）+ 明确"settled 之前的事实已持久"边界（已具备，见 §1.3）。
- 若维持 fail-open 观测可用性优先，则 RI-1 文本须显式降格为 best-effort + orphaned 可解释。
- **建议**：维持 shadow fail-open 为主承诺，orphaned 标记作为 P0-3 最小机械动作补齐可解释性。

### Q3 窗口量化
- P0-3 启动时用 audit §5 同型查询统计现存日志 `opened-without-settled` 真实分布（按 provider/时间），作为裁决 Q1 范围与 Q2 成本的输入。当前无预跑数据，不预判量级。

## 3. 明确不做

- 不回填 outcome / 不猜测 finish_reason；
- 不为 durability 改变 transport 同步语义（观测不为事实让路）；
- 不在 P0-2 内实现（本文仅输入）。
