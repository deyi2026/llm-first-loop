# DESIGN-20260910：Episode-driven Learning Plane（ReflectionRun · 前台优先 admission · runtime-derived provenance）

> 状态：Learning Plane 专项实施设计。取代同日 v1（`reflection-session-decoupled-learning.md`，已标 SUPERSEDED）。
> 总 Architecture SoT：`DESIGN-20260910-adaptive-reasoning-learning-architecture.zh.md`。
> 若本文与总 SoT 的四平面 + Meta-Learning / provider-agnostic Resource Governor / 实施顺序发生冲突，以总 SoT 为准。
> P0 feature-candidate qualification：`analysis/QUALIFICATION-20260910-learning-plane-p0.md`（通过不等于 production rollout）。
> 依据：用户第二轮拷问（九问）裁决 + 两轮代码证据。本地文档，不进公开仓库索引。
> 分支：`feature/learning-plane-20260910`（不混入 context-elasticity 旧线）。

## 0. 裁决摘要（三个 P0）

1. **P0-1 反思移出用户 critical path**：`post_run`（engine.py:1488）仅做本地入队；durable
   LearningJournal + 进程内 LearningCoordinator 异步消费；`done` 不再等 reflection
   （现状最坏 ~240s：2 次串行 chat × 120s）。
2. **P0-2 学习材料与 provenance 的单位升级为真实 episode**：
   - 材料面：EpisodeStore hydration（可见 user/assistant/tool，明确无 `reasoning_content`）
     取代 `sess.messages[-36:]` 截断——跨任务污染发生在源材料选择阶段，换 Session 解决不了；
   - provenance：`save_candidate` 的 `source_episode_refs` 必须 runtime-derived；qualification
     独立性由程序计算的 episode lineage 证明，模型自由 `task_ref` 一律不采信。
3. **P0-3 单并发本地模型（8901 prompt-concurrency=1）上 learning 仅 idle 启动**：quiet period
   + 活跃 run gate；已进入的调用不可抢占——如实记录，不假装"零影响"。

## 1. 为什么是 ReflectionRun 而不是"另一个 Session"（Q2）

ReflectionRun 是学习运行，不是聊天会话。显式**不含**：user channel / messages 语义 /
parent-branch / model_override / history anchor / summary_chain / projection guard /
working_state_checkpoint / session title / Web 会话列表 / 普通用户 ingress。防止 Session 生态
（历史压缩、缓存 anchor、session_busy、continuity、memory、branch）隐性作用于学习。

```
ReflectionRun {
    learning_job_id, source_episode_ref, source_session_id, source_model,
    trigger_facts, feedback_refs, state, attempt, candidate_ref, error,
    created_at, started_at, finished_at
}
```

## 2. 数据流

```
Task Session → persist_and_settle（episode 落定，ref 写回 user message metadata）
  → post_run：读 resolved_episode_ref + friction facts
     → LearningJournal.append(queued)               ← 纯本地写，零 LLM
     → 用户会话记一条 learning.enqueued 指针事件
  → return LoopResult → SSE done → lease 释放       ← 用户路径到此终结
────────────────────────────────────────────────────
LearningCoordinator（daemon 线程）
  扫 journal queued → admission（见 §5）→ admitted → started
  → EpisodeStore hydration → reflect（tools=[]）→ saved(candidate_ref) | none | failed
Reconcile（启动时）：started 无 terminal → 查 MethodStore 是否已有
  source_learning_job_ref 匹配 candidate → saved；无 → 重跑（attempt≤2）。
  防同 episode 二次生成措辞不同的重复 candidate。
```

实施注记：`resolved_episode_ref` 已由 RunFinalizer 写回 user message metadata
（`episode_history.py:59,991,1013`）——入队点直接读，**无需改 finalizer**。

## 3. 权力边界（三 Plane，写死）

- **Task**：理解 → 行动 → 回答 → 完成。不承担学习。
- **Learning**：观察 → 反思 → 抽象 → candidate。只读 Episode/Evidence/Method hydration；
  无普通工具（`tools=[]`）；唯一写能力 = save Method candidate；不碰用户 Session、不抢
  lease、不写用户事件流（除 done 前的 `learning.enqueued` 指针）。
- **Qualification**：独立 episode 验证 → refine/qualify/invalidate。Reflection 永远不能给自己
  晋级；程序证 lineage（身份与来源），模型判意义（是否有效/有益/值得 promotion）。

## 4. Provenance 细则（P0-2）

- reflection（deferred 路径）：`source_episode_refs=[source_episode_ref]`（真 episode），另记
  `source_learning_job_ref`、`source_model`（runtime-derived）。现 `reflection.py:189` 的
  `[f"session:{session_id}"]` 是系统性伪 provenance，废除。
- `registry_experience.save_candidate`（run 中途工具）：`stable_episode_ref(session_id,
  user_message, user_seq)` 是确定性纯函数（episode.py:66-80），run 中途即可算出与最终落定
  相同的 ref——**无时序问题**，程序当场计算，不信模型自报。
- `record_qualification`：程序写 `qualification_episode_ref=stable_episode_ref(当前 human
  turn)`；model-facing schema 不再提供 `task_ref`，存量/额外 caller 字段即使出现也被忽略，
  不能参与 identity/independence 证明。`store.py:264` 的字符串包含检查升级为
  lineage 检查：qualification_episode_ref 与 candidate 源同 ref / 同 session 同 user_seq →
  reject。fork/derived 链留 P1。
- 兼容：存量 `["session:..."]` 只读兼容，不回写。

## 5. 资源边界（P0-3）

- admission 序：queued →（now − last_run_end < idle_s）等待；`BackgroundRunner.has_running()`
  （runner.py:180）或 `engine._sync_active` 非空 → 让路（不忙等，下轮再查）；两阶段——
  admitted 后、**每次模型调用前**再查，等不到重排队。
- 物理事实声明：进入单并发 8901 的 reflection 不可抢占；learning 请求 low-priority /
  non-pin / transient，绝不因 Method Learning 拿长期 cache pin。
- 未来升级（P2）：可取消 background priority；或 trust-domain 授权的学习 provider 路由
  （决策树：source trust domain → allowed learning providers → scheduler；禁止反思模型自选
  provider——不能因为"云端空闲"就把本地私有任务发出去）。
- 无干扰资格验收（P2）：真实 A/B（OFF vs ON）测 TTFT / cache_hit_tokens / prefill latency /
  foreground queue delay；只看 done 及时不算数。

## 6. Closed schema（P1）

`_valid_candidate`（reflection.py:88-91，现只查 name/description/body 非空）升级为 closed
schema：`decision / name / description / trigger / discriminator / short_path[] /
stop_conditions[] / verification[] / counterexamples[] / program_boundaries[] /
model_owned_judgments[]`。程序只验存在+类型+长度，不判内容质量；MethodStore 机械渲染
Method Card。存量自由 body 兼容读。

## 7. 触发器面（P1）

- 机械 friction（现有 OR 条件）保留。
- 新增机械触发：Web feedback **downvote**（routes.py:1560-1620，durable
  `data/feedback.jsonl`，纯审计数据）→ 为对应 session 最近 episode 入队。
- 关键词式"用户纠正"检测显式**不做**（语义归模型）。相邻 followup 材料：程序只证明
  "紧邻的真实用户消息"（previous_episode_ref + adjacent genuine user message），纠错/补充/
  换题的判断归 Reflection 模型。

## 8. 配置（挂 config.py:404-408 邻域，三件套模式）

```
METHOD_LEARNING_EXECUTION=deferred|inline|off   # 默认 deferred；inline 仅回滚开关，P3 删
METHOD_LEARNING_IDLE_S=15                       # quiet period
METHOD_LEARNING_JOURNAL=data/method_learning/jobs.jsonl
METHOD_LEARNING_MAX_ATTEMPTS=2
```

既有 `METHOD_REFLECTION_MODE/MIN_*/TIMEOUT_S` 语义不变（deferred 路径复用触发与超时）。

## 9. 分期

- **P0-A（本分支首批）**：LearningJournal + reconcile、episode 驱动 reflect、post_run 入队 +
  `learning.enqueued`、Coordinator + idle admission、reflection provenance、execution 开关。
  验收：done 时延不再含任何 LLM 调用；reflection 不写用户事件流（除 enqueued）；
  ruff/mypy/pytest 全绿。
- **P0-B**：registry_experience provenance + store lineage 检查 + 存量兼容。
- **P1**：closed schema、downvote 触发、跨进程 `*.run.lock` 探测、旧 `method.reflection`
  用户事件退役。
- **P2**：cache 干扰 A/B、fork/derived lineage、method_search/method_get 只读窄工具、
  学习 provider 路由。
- **P3**：删 inline 路径。

## 10. 显式不做

- ReflectionRun 不获得普通 Agent 工具面（60+ 工具）；v1 `tools=[]`，未来最多两个只读窄工具。
- 不做关键词纠正检测；不做模型自证独立性；不跨 provider 自动外发；不占 session_busy /
  不持用户 run lease；done 之后零写用户会话。

## 11. 开放问题

已裁决：载体=ReflectionRun；指针事件保留；材料单位=episode；inline 保留作回滚开关。
留待：journal 清理策略（按 episode 幂等去重 + 滚动保留）；idle_s=15 的实测校准（P2 A/B 定）。
