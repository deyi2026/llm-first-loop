# DESIGN-20260910：Task Session 与 Method Learning 彻底解耦（Reflection Session + 优先级调度）

> **[SUPERSEDED 2026-09-10]** 本 v1 初稿的"独立 LearningSession（复用 Session 对象）+
> enqueue 时冻结材料包"方案，经用户第二轮拷问（9 问）被裁决推翻：
> (a) 材料面改为 **EpisodeStore hydration**（真实 `episode:` ref，废 sess.messages 截断）；
> (b) 载体改为 **ReflectionRun**（独立学习运行，非普通 Session 对象，避免 8+ 项隐性耦合）；
> (c) 增加 runtime-derived provenance / qualification lineage 防伪、closed schema、
> durable journal reconcile、feedback 触发器、cache 干扰 A/B 等节。
> 终版见 `docs/DESIGN-20260910-learning-plane.md`。本文件仅存档，勿再引用。

> 状态：设计稿（待评审）。本地开发文档，按 2026-08-14 公开面原则不进公开仓库索引。
> 前置讨论：用户提出方向（任务完成与学习解耦、独立 Learning Session、Foreground > Learning
> 调度、candidate 不得自我晋级）；本文给出代码级落地设计。

## 0. TL;DR

当前 `post_run` 反思在 run 生成器内部**同步调用 LLM**（最多 2 次串行 chat，各 120s 超时），
且发生在 `return LoopResult` 之前——`done` 事件、run lease 释放、session_busy 清除全部被
卡在后面；本地 8901（prompt-concurrency=1）还会被反思占用，导致用户下一条消息排队。

改法：run 结束路径只做**入队**（纯本地写，无 LLM 调用）；反思由独立 **LearningSession**
（`session_type=learning`）在低优先级 worker 中执行，材料来自 enqueue 时冻结的只读
**学习材料包**；任何前台/子代理 run 活跃时反思让路。candidate 生命周期不变。

## 1. 问题确认（证据链）

- `.env:223` `METHOD_REFLECTION_MODE=auto`（生产已开启；`.env.example:123` 默认 off）。
- 触发条件是 **OR 语义**（`src/llm_loop/methods/reflection.py` `should_reflect`）：
  rounds≥6 ∨ tools≥6 ∨ failures≥2 ∨ duplicates≥2 ∨ stagnation/max_iterations——工具型
  任务几乎必触发。
- 阻塞链：
  1. `engine.py:1488` `self._method_learning.post_run(...)` 在 `return LoopResult` 前同步执行；
  2. `method_learning.py` → `reflect_after_run`（`reflection.py`）最多 **2 次串行**
     `client.chat`（首次 + teacher fallback，`reflection.py:92-101, 174-179`），每次
     `timeout_s=120`（`METHOD_REFLECTION_TIMEOUT_S=120`）→ 最坏 ~240s 无反馈；
  3. 后台线程在生成器 StopIteration 后才发 `done`（`runner.py:510-511`）；
  4. run lease 持有到 `finally`（`lifecycle.py:136, 181`），期间 session_busy；
  5. 本地 8901 prompt-concurrency=1：反思占用模型，新前台请求排队其后。
- 用户感知（"模型没结束/没有结束动作"）：`done` SSE 是存在的结束动作，但被 3/4/5 拖住
  数十秒到 240s。第一轮假设"缺结束信号"由本证据链否定，反思同步调用是根因。

## 2. 设计原则（已与用户对齐，固化）

1. 任务 Session：理解 → 行动 → 回答 → 完成（done 即终结，之后不再改写用户会话）。
2. ReflectionSession：观察已完成 episode → 反思 → 抽象 → 生成 candidate。只读源任务
   快照，无权修改源 Session。
3. Qualification 不变：换 Session ≠ 独立验证。同一 source episode 不能给自己的 candidate
   晋级（candidate → 新任务验证 → qualified/refine/invalidate 路径不动）。
4. 调度优先级：**Foreground（用户 run）> SubAgent > Method Learning**。学习永不占
   session_busy、不持用户 run lease、不阻挡新 run。
5. 学习材料**不包含 raw hidden chain-of-thought**（与 Method Learning 既有原则一致）。

## 3. 架构总览

```text
用户任务 Session（不变）
    run：deltas … → persist_and_settle
      ↓
    enqueue LearningJob（纯本地写：材料包 + job 记录 + 指针事件）   ← engine.py:1488 改造点
      ↓
    return LoopResult → SSE done → lease 释放 → 8901 让出
    ──────────── 用户任务彻底结束 ────────────

Learning Worker（进程内低优先级线程，可多进程共存）
    扫描 pending job → claim（跨进程 lease）
      ↓ 等待：quiet period ∩ 无活跃 run（进程内 registry + 跨进程 run.lock 探测）
    ReflectionSession（session_type=learning）
      只读材料包 → reflect_after_run（复用现函数，含 teacher fallback）
      → save_candidate（source_episode_refs 指回 source run）
      → 结果写入自身事件流；job → done
```

## 4. 组件设计

### 4.1 任务侧：engine.py:1488 改为入队

- `post_run` 拆成两段：
  - `build_reflection_material(...)`：由 `sess.messages` 快照 + LoopResult friction +
    provenance 构建材料包（纯 Python，无 LLM）；**enqueue 时冻结**，之后源会话再变不影响。
  - `enqueue_reflection_job(material)`：追加 `data/method_learning/jobs.json`
    （文件锁 + 原子重写，模式沿用 `schedule.json` 的 claim/lease 编码，见
    `core/scheduler.py`；不共用其文件）。
- 入队失败**只记日志/异常流**，绝不影响 `return LoopResult` 与 `done`。
- 用户会话在 done 前追加一条轻量指针事件 `learning.enqueued`（含 job_id、
  source_run_id），此后不再有任何 post-done 写入（现 `method.reflection` 事件迁出，
  见 4.3）。
- 去重：job 以 `source_run_id` 为唯一键，重复入队幂等合并；队列上限（默认 64），
  超限丢最旧并记 `learning.dropped`。

### 4.2 LearningJob 数据模型

`data/method_learning/jobs.json`（单文件，锁内整读整写）：

```jsonc
{
  "job_id": "lrn-<ts>-<uuid8>",
  "source_session_id": "...", "source_run_id": "...",
  "state": "pending|claimed|done|failed|dead",
  "attempts": 0, "max_attempts": 3,
  "lease_owner": "", "lease_until": 0.0,      // 跨进程 claim，沿用 scheduler 模式
  "enqueued_at": 0.0, "last_attempt_at": 0.0,
  "material": { ...学习材料包，见 4.4... },
  "error": ""                                   // 失败原因（截断）
}
```

### 4.3 ReflectionSession（session_type=learning）

- Session 模型加 `session_type: str = "user"`；learning 会话 id 形如
  `learn-<ts>-<uuid8>`，正常落 SessionStore（`core/session.py` save/load 透明兼容）。
- 默认从 Web/CLI 会话列表过滤（`?include=learning` 才可见），不进用户上下文、不参与
  cache prefix——它是一次性内部对象，不是可续聊会话。
- 持有自己的 `learn.lock`（防多 worker 同跑同一 job），**永不获取任何用户会话的
  run lease**。
- 事件流归属：`method.reflection`、`method.candidate_saved`、`learning.job.*` 全部写入
  learning 会话的 event log（`data/event_logs/`），源用户会话零污染。
- 学习完成后唯一的跨写：`methods/store.py save_candidate(...)`，
  `source_episode_refs=[source_run_id]`（保持"同一 source episode 不能自我晋级"可判）。

### 4.4 学习材料包（enqueue 时冻结；不含 hidden CoT）

| 字段 | 来源 |
|:---|:---|
| `source_session_id / source_run_id` | run 上下文 |
| `task` | 本轮用户输入（首条 user 消息） |
| `final_answer` | 最后一条 assistant 消息 |
| `messages` | 工具调用与（截断后）工具结果，压缩策略沿用现 reflection prompt builder |
| `friction` | rounds / tool_calls / failures / duplicates / end_reason（现 friction dict） |
| `loaded_methods / skills` | run provenance |
| `model` | `result.model_used`（provider/model provenance） |
| `snapshot_sha256 / acquired_at` | 完整性自校验 |

明确排除：raw hidden chain-of-thought；完整用户 history（非本轮内容）。

### 4.5 调度：Foreground > SubAgent > Learning

- **进程内 gate**：`engine._run_registry.active()`（`runner.py:492` 已在用）——任何
  活跃 run（前台或 subagent）存在时，worker 不发起 chat。
- **跨进程 gate**：非阻塞探测 `data/sessions/<sid>.run.lock`（与 `run_lease` 同机制，
  `core/session.py:660`）——CLI 与 Web 并存时同样让路。
- **检查粒度**：每次 `client.chat` 前检查；首次调用与 teacher fallback 之间再查。
  HTTP 调用一旦发出不可抢占，由 `timeout_s` 兜底。
- **quiet period**：入队后需满足 `now - last_run_end ≥ METHOD_REFLECTION_QUIET_PERIOD_S`
  （默认 15s）且无活跃 run，才开始——避免在用户连续两问间隙抢 8901。
- **让路语义**：等待中被前台超越属正常；等待超上限（如 10 分钟）→ job 重新入队
  （`attempts+1`），不做忙等。反思对材料包幂等，重跑无副作用。

### 4.6 可观测性

- 新事件（learning 会话流）：`learning.job.started / retried / done / dead / dropped`。
- 新 API：`GET /api/learning/jobs`（队列状态，排障用）。
- UI（可选，P2）：done 后右上角小标记"learning…"，不阻塞输入框；完成即隐。

## 5. 失败与恢复

- Worker 崩溃/进程重启：启动时扫描 `pending` 与过期 `claimed`（`lease_until` 超时）重新
  可领取；`attempts` 递增，达 `max_attempts=3` → `dead`（留档可查，不重试）。
- 反思 LLM 失败/JSON 无效：沿用现有 teacher fallback 与放弃路径，结果只影响 job 状态。
- 任何 learning 路径异常都不冒泡进用户 run（入队点 try/except 全包）。

## 6. 配置与兼容

```text
METHOD_REFLECTION_MODE             = auto|off（既有，.env:223 现=auto）
METHOD_REFLECTION_EXECUTION        = deferred|inline   # 新，默认 deferred；inline 仅为
                                                    # 旧行为/既有测试保留，P3 删除
METHOD_REFLECTION_QUIET_PERIOD_S   = 15
METHOD_REFLECTION_MAX_ATTEMPTS     = 3
METHOD_REFLECTION_QUEUE_MAX        = 64
```

回滚：`METHOD_REFLECTION_EXECUTION=inline` 立即回到旧行为；`MODE=off` 全关。

## 7. 实施步骤（小步 PR）

- **P0 止血**：engine.py:1488 → 材料包 + 入队（无 LLM）+ 进程内 worker（仅
  `_run_registry` gate）。`done` 即发。改动最小、当天可用。
- **P1 健壮**：跨进程 run.lock 探测、quiet period、attempts/重入队、重启恢复、去重与
  队列上限。
- **P2 完整 ReflectionSession**：`session_type` 字段、事件流迁入、`/api/learning/jobs`、
  UI 小标记。
- **P3 清理**：删 inline 路径与 `method_learning.py` 旧同步 LLM 调用（`reflect_after_run`
  函数本身保留复用）。

## 8. 测试计划

1. `test_done_not_blocked`：fake client 睡 30s；mode=auto+friction 触发；断言 `done`
   在反思完成前发出，candidate 最终落库。
2. `test_no_user_session_mutation_after_done`：done 后 worker 完成全程，用户会话事件
   不新增（除 done 前 `learning.enqueued`）；`method.reflection` 出现在 learning 会话。
3. `test_priority_gate`：registry 有活跃 run → 不发 chat；run 结束 → 启动。
4. `test_preempt_between_calls`：两次 chat 之间出现前台 run → 第二次让路、job 重排。
5. `test_crash_recovery`：模拟 worker 中断重启 → job 恢复、attempts 生效。
6. `test_dedupe_and_queue_max`：同 run 重复入队幂等；超限丢旧。
7. `test_material_no_hidden_cot`：材料包 schema 断言无 hidden 字段。
8. `test_cross_process_gate`：手工创建 `*.run.lock` → worker 等待。

## 9. 被否决的备选

- **仅把 post_run 丢进 executor/线程**：SSE/lease 可解，但用户会话仍被追加
  `method.reflection` 事件（done 后写文件，与下一轮 run 并发写竞争），本地 8901 仍可能
  被反思占用抢新请求，且无优先级语义。
- **Web 层在 done 之后再调 post_run**：session_busy 已清除，反思与用户新 run 并发写
  同一会话事件流；仍占模型；且 CLI/飞书等其他入口要各改一遍。

## 10. 风险与开放问题

- learning 会话数量随时间增长 → 归档策略（复用 archived_sessions 机制）待定。
- 多进程 worker 同时跑不同 job 在云端 provider 无害；本地单模型下靠 run.lock 探测
  规避，极端时序仍可能短暂并发一个前台+一个反思调用（8901 服务端排队，可接受）。
- 指针事件 `learning.enqueued` 是否保留在用户会话（默认保留，便于追溯；可在评审时
  决定去掉以追求绝对零写入）。
