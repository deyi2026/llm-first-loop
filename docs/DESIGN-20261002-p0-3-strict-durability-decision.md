# P0-3 Strict Durability 裁决与实现方案

Date: 2026-10-02
Status: **IMPLEMENTED（2026-10-02，§5 四项全落地：脚本 + hydration + snapshot + 回归；单文件层 8/8 标记；多段层归属已裁决收口：根因 fork 物理继承，48 个定性历史 settle-loss，47 原生标记 + 1 副本跳过，累计 55，重跑 0 新增，见 §7 与归属 mini-design）**
裁决输入：`docs/DESIGN-20261002-p0-3-gap-dur-1-strict-durability-input.md`
权威：`docs/DESIGN-20261001-model-invocation-history-replay-safety.md` v1.1 RI-1（L118）
上游计划：`docs/DESIGN-20261002-p0-2-provider-settlement-coverage-plan.md` §2 GAP-DUR-1

> 引用修正：裁决输入 L6 的上游路径写作 `DESIGN-20260930-...`，实际权威文件为
> `DESIGN-20261001-model-invocation-history-replay-safety.md`（20260930 为未提交草稿旧名）。

## 1. Q3 窗口量化（2026-10-02 实测，全量 event_logs 539 文件）

| 指标 | 值 |
|---|---|
| `provider.transport.opened` 总数 | 4,335 |
| opened-without-settled（孤儿） | **8（0.18%）** |
| 孤儿 provider 分布 | cognilocal 6 / glm 2 |
| 孤儿时间分布 | **全部落在 2026-09-11 ~ 09-13**（8 个不同 session） |
| 09-13 之后新增孤儿 | **0** |

结论：孤儿是**历史遗留一次性事实**（旧版本时期进程中断遗留），不是持续产生的问题。
单条会话最多 1 个孤儿；无一 session 多孤儿。

## 2. Q1 裁决：孤儿 reconciliation

| 待裁决项 | 裁决 | 理由 |
|---|---|---|
| 扫描范围 | **全历史一次性** | 总量 8 条零成本；"仅最近崩溃 session"需先定义"崩溃"判据，复杂度反超收益 |
| 标记形态 | **追加 `provider.transport.orphaned` 事件到对应 session 日志** | 事件流是事实源；audit §5 同型查询直接闭合 opened→orphaned，无需跨文档对齐 |
| 扫描时机 | **显式脚本，非进程启动钩子** | 一次性历史事实不值得每次启动付扫描；启动期写别的 session 日志扩大权限面 |
| outcome 回填 | **不回填**（维持） | 程序不伪造结局；unknown 保持 unknown |

payload 机械字段（对齐 `_attempt_identity_payload`）：

```json
{
  "call_id": "pcall:...", "attempt_id": "pattempt:...",
  "provider_id": "...", "model_id": "...",
  "opened_at": <从 opened 事件取>, "orphaned_at": <标记时间>,
  "mechanical_fact": "opened_without_settled"
}
```

不写 reason/cause 字段——崩溃具体原因（kill -9/OOM/断电）不可机械判定，写即伪造。

## 3. Q2 裁决：RI-1 与 fail-open 的关系

**两轴分离**：fail-open（settlement 异常不阻断 transport，观测可用性轴）与
strict durability（崩溃窗口事实不悬置，持久性轴）是独立属性，不互斥不对冲。

- **维持 fail-open** 为 transport 可用性承诺（`provider_settlement.py` L162 契约不变）。
- **fail-open 期间不宣称 RI-1**（v1.1 L118 原文锁定："fail-open 期间不得宣称 RI-1"）。
- **strict durability policy 定义**（即宣称 RI-1 的条件）：
  1. prepared write-before-send（✅ 已具备，audit D3）；
  2. 孤儿 reconciliation：opened-without-settled 在已知后标记 orphaned（本方案 §2）；
  3. 诚实语义：RI-1 承诺形态为 **"每次 attempt 有 prepared + settled-or-orphaned"**，
     不是"每次都有 settled"。崩溃前 outcome unknown 是可解释终态，不是悬置。

## 4. 事实修正（对裁决输入的更正）

1. **§1.4 settle 幂等语义不完整**：`settle_transport_attempt`（L445）对同 attempt_id
   **内容相同**的重复 settle 是幂等返回 existing（L495-497），仅可比较字段冲突时才
   raise（L532-533）。这不改变"孤儿不回填"结论——outcome 内容不可知，无法构造
   内容相同的 settle——但防止把 raise 语义误读为防重入屏障。
2. **§L6 上游路径错误**：见文首引用修正。

## 5. 实现方案（最小机械动作）

| # | 动作 | 位置 | 验收 |
|---|---|---|---|
| 1 | 孤儿标记脚本（幂等：已 orphaned 不重复标） | `scripts/evidence/mark_orphaned_transport_attempts.py` | 对全量日志跑后孤儿计数 → orphaned 计数 = 8；重跑 0 新增 |
| 2 | journal hydration 识别 orphaned 事件 | `provider_settlement.py` `_hydrate_call_locked` | orphaned attempt 从 `_opened_attempts` 语义中移出（见下） |
| 3 | `snapshot_call` 区分 orphaned | 同上 | `attempts_orphaned` 计数字段；`attempts_complete` 不把 orphaned 算 settled |
| 4 | 回归测试 | `tests/unit/test_provider_settlement.py` 或新文件 | fixture 构造 opened-无-settled → 脚本标记 → 断言事件追加且幂等；hydration 后 snapshot 口径正确 |

不改：transport 同步语义、4 个既有事件、fail-open 行为。

## 6. 明确不做

- 不为孤儿回填 outcome / finish_reason / usage（伪造）；
- 不把 orphaned 标记做成常驻后台任务（一次性事实）；
- 不在 P0-3 内动 RI-2/RI-3/RI-5（各有独立 seam）。

## 7. 实施期新发现：多段 session 层复制 artifact（2026-10-02，**已裁决并收口**）

实施全量扫描时发现 §1 的测量口径只覆盖**单文件 session**（`<sid>.jsonl`，539 个，
4,335 opened——与 §1 表格完全一致）。多段 session 目录（`<sid>/<seg>.jsonl`，64 个）
从未进入测量，其中另有 **48 个 opened-without-settled**（时间跨 09-16 ~ 09-22，
glm 为主，attempt 后 session 仍有后续事件——非崩溃形态）。

决定性证据：多段层存在 **1,189 个 attempt_id 跨 session 完整重复**（同微秒 ts、
同 call_id、payload 逐字段一致），即事件被复制进多个 session 目录。~~对它们打
orphaned 标记会把未裁决的复制问题固化为孤儿事实~~（该担忧已被归属裁决消解）。

~~处置：脚本默认只扫单文件层；`--include-multi-segment` 显式开关保留给未来归属
裁决后使用。多段层归属/去重需要单独 mini-design，不在本 P0-3 范围内。~~

**2026-10-02 归属裁决收口**（用户 09:50 授权执行建议；详见
`docs/DESIGN-20261002-multisegment-fork-inheritance-attribution.md`）：

1. 重复根因 = `session-fork` 物理继承（fork.py 保留 type/ts/payload，仅重分配
   seq/event_id/session_id）；1,203 个重复 attempt_id 全部落在这 3 对 fork 谱系
   （32d694c9↔e89b29b3 = 1,189，与上文精确对账），**0 个无解释重复**；
2. 48 个 opened-without-settled **不是复制 artifact**：settled 在所有 session 中
   均不存在（fork 截断假设被证伪）；定性为历史 settle-loss（fail-open settle
   静默丢弃路径，09-23 起归零）；
3. 标记规则冻结：settle-anywhere 守卫 + fork 副本（seq < session.forked marker）
   跳过，仅标记原生出现。真实数据执行结果：**marked 47（glm 46 + cognilocal 1）、
   replicas_skipped 1、累计 orphaned 55（含单文件层 8）**；幂等复跑 0 新增。

§1"孤儿是历史遗留一次性事实"的结论在多段层被证伪——那是测量盲区，不是事实变化；
修正后结论：孤儿（opened-without-settled）在两层合计 55 个，全部落在 2026-09-11 ~
09-22，此后零新增。
