# LFL 开发与修复防退化手册

> **适用对象**：修改、重构、调参、迁移或修复 LFL / Provider / Continuity / History / Cache / Tool / Web / SubAgent / Runtime 的维护者与 Agent。
>
> **规则入口**：`RULE-AI-24`。
>
> **定位**：这是 maintenance/development contract，不进入普通用户 run 的 universal prompt。程序提供能力、事实、边界和可恢复性；模型负责语义理解、策略、取舍与完成判断。

## 0. 为什么这份手册必须存在

近期连续性与本地模型优化中出现过一组表面不同、根因高度一致的事故：

- 模型看起来“变笨/空响应”，实际是把另一 runtime 的 `max_tokens=4096` 默认值照搬到 GGUF，reasoning 在达到正文前先耗尽输出预算；
- 模型看起来“刚说完就忘”，实际是 completed episode 被过早从 provider-view 退休，下一轮只剩极短 history；
- 截断内容“有保存”，但只有 overwrite-only sidecar 或短 tail，没有长期、稳定、模型可水合的 exact ref；
- 长附件原始 bytes 在盘上，但模型只有 2K excerpt，没有自主回读全文的入口；
- 第二次主动回读长文仍被同一展示预算再次截到头部，形成“永远只看到第一页”的假恢复；
- preview 被送去做 LLM 摘要，却被称为“全文语义摘要”；
- durable AttachmentStore 放在 Web 层，导致依赖方向和 local-import ratchet 出问题；
- 全仓测试在 unstaged working tree 上看似全绿，但架构守卫回退读取旧 HEAD，提交后才暴露真实候选违规。

这些事故的共同教训不是“需要更复杂的控制器”，而是：**不要让程序静默丢信息、替模型做语义裁决，或把未验证的历史经验冒充当前 runtime 事实。**

---

## 1. 开发/修复前六问硬门

任何行为修改在落代码前必须能回答下面六问。任一项回答不清楚，先取证，不直接补丁。

### Q1. 完整事实源还在吗？

- 任何 `[:N]`、head/tail、projection、compact、summary、preview、budget 裁剪之前，完整源在哪里？
- 是 exact bytes/text，还是只有派生片段？
- `snapshot_complete` 与 `source_complete` 是否被区分？

**红灯**：先截断再保存；只有 preview/tail 却声称“原文已保存”。

### Q2. 模型以后真的找得到并读得回来吗？

“文件在磁盘上”不等于“模型可恢复”。必须闭合：

`durable source -> stable ref -> searchable/discoverable -> authorized exact hydration -> monotonic paging`

第二次显式回读时：

- 能在真实物理上限内一次返回，就返回完整内容；
- 确实超限才分页；
- `next_offset` 必须单调前进；
- 不得再次套初始 excerpt/projection，重复第一页。

### Q3. 模型所谓“忘了/重复/变笨/空响应”，它实际看到了什么？

先检查真实 provider-view / request payload / runtime receipt，再讨论模型能力：

- 最近 human/assistant pair 是否还在下一轮？
- tool result / reasoning / attachment 是否被程序投影掉？
- role 顺序是否改变？
- 是否发生 timeout/retry/duplicate request？
- 输出预算是否在 reasoning 阶段耗尽？

**禁止**：没有检查模型实际输入，就先加 prompt、换模型、提高 temperature、增加“记住上文”训诫。

### Q4. 参数和行为是在“当前 runtime”验证过的吗？

跨 backend/runtime 只能复用**需求和实验起点**，不能复用“等价结论”。

以下参数必须按当前 runtime qualification：

- `max_tokens` / context window
- reasoning mode / reasoning replay
- temperature / top_p / top_k / min_p
- cache/KV 行为
- chat template / tool-call wire behavior
- timeout / streaming finish semantics

**禁止**：把 MLX、llama.cpp、vLLM、LM Studio 或另一个 provider 的 launcher 默认值直接写成 parity profile。

### Q5. 程序是不是开始替模型做语义判断？

程序可以判断：

- 字节/token/内存是否物理装不下；
- ref 是否存在、SHA 是否匹配；
- 当前是 queued/running/cancelled/completed；
- source 是否完整、offset 是否前进；
- 安全、授权、数据完整性和真实资源边界。

程序不应判断：

- 哪段语义“重要”；
- 哪个历史片段“应该进入 prompt”；
- 当前任务“已经完成”；
- 哪段 reasoning“值得自动 replay”；
- 什么时候“应该自动总结”；
- 哪个模型“语义上更适合”但没有模型/用户作出该决定。

**口诀**：程序保真、保边界、保可恢复；模型做语义、策略、取舍、完成判断。

### Q6. 验证的是最终 candidate，还是旧 HEAD / 错环境 / 假绿结果？

最终验收必须证明测试看到的是**准备提交的现实**：

- 使用项目 `.venv`，不要把系统 Python 缺依赖误判成项目缺依赖；
- shell 管道必须保留原命令 exit code（`set -o pipefail` 或不用管道）；
- 有双口径/HEAD fallback 的架构守卫时，对 staged candidate 或 isolated worktree 运行；
- 不能因为测试红就先抬 baseline / 加豁免；先判断 guard 是否在揭示真实职责问题；
- runtime 修改必须验证 `source config -> live process -> backend actual request facts` 三层一致。

---

## 2. 必须避开的 18 个坑

### 2.1 跨 runtime 复制默认参数

**坑**：另一个 launcher 能跑，所以把默认 `max_tokens` / sampling / cache 参数照搬。

**后果**：模型能力被人为限制，却被误诊为模型退化。

**替代**：每个 runtime 独立 qualification；历史值只作为实验起点。

### 2.2 模型“健忘”先怪模型

**坑**：加“记住上文”prompt 或换模型。

**后果**：真正的 history/provider-view 裁剪 bug 被掩盖。

**替代**：比较上一轮结束与下一轮 request 的实际 provider-visible messages/chars。

### 2.3 把 completed 当成“下一轮不需要”

**坑**：resolved episode 一完成就从工作面完全退休。

**后果**：自然语言跨轮指代链断裂。

**替代**：按机械邻近关系保留 recent dialogue working set；更老内容再按需检索。

### 2.4 先截断，再保存

**坑**：保存的是 `result[:N]`、tail 或 preview。

**后果**：第一次截断之后永远无法准确恢复。

**替代**：`exact capture -> stable ref/SHA -> projection`。

### 2.5 第二次读取仍用第一次展示预算

**坑**：模型主动回读 40K 原文，仍只返回 2K/5K。

**后果**：形成重复回读、工具循环和“怎么都找不到”的假象。

**替代**：explicit recovery 走 control plane；物理允许时一次完整返回，超限只做不重叠分页。

### 2.6 “已落盘”冒充“模型可用”

**坑**：数据存在 JSONL/sidecar/文件中，但没有稳定 ref 或 hydration 工具。

**后果**：恢复能力只对人类运维存在，对模型不存在。

**替代**：必须闭合 discover/search + exact read + scope authorization。

### 2.7 用 preview 冒充全文摘要

**坑**：800 chars preview -> LLM -> “全文语义摘要”。

**后果**：摘要的权威性高于实际覆盖范围。

**替代**：摘要必须绑定 exact `source_ref + source_sha256 + coverage`；摘要是 derived view，不替代原文。

### 2.8 自动摘要/自动 working-state 悄悄变成语义控制器

**坑**：程序看到“长了/快截断了”就自动决定何时总结、总结什么、注入哪里。

**后果**：程序重新成为第二大脑，并可能与主模型竞争单-slot runtime。

**替代**：先提供 `source_synopsis` 等能力；自动 producer 必须独立设计、独立 qualification，默认 HOLD。

### 2.9 混淆 snapshot 完整与 source 完整

**坑**：完整保存了 16K 中断 reasoning，就标记“source complete”。

**后果**：模型被错误元数据误导，以为整个生成/文档已覆盖。

**替代**：至少区分 `snapshot_complete` 与 `source_complete`。

### 2.10 derived view 权限跟着 source 自动扩大

**坑**：workspace-scoped 文件的模型摘要自动跨 session 可见。

**后果**：摘要可能携带当前会话信息，形成隐私扩权。

**替代**：派生物权限不高于产生它的上下文；跨 scope 复用必须显式 promotion。

### 2.11 持久化能力放错层

**坑**：durable store 放在 Web/UI 包里。

**后果**：factory 循环依赖、局部 import、职责倒置。

**替代**：问“没有 Web 这个能力还存在吗？”如果存在，存储应落在中性 core/memory/workspace 层，Web 只是 adapter/facade。

### 2.12 修完事故只写总结，不写回归

**坑**：经验只留在聊天或文档。

**后果**：下一轮重构再次删除同一能力。

**替代**：每个真实 incident 转成最小 regression case；尽量使用真实对话/长度/状态形状。

### 2.13 测试验证了旧 HEAD，不是候选

**坑**：working tree 的架构守卫把 unstaged 文件当外部漂移并读 HEAD。

**后果**：commit 前假绿，commit 后才红。

**替代**：最终 gate 在 staged candidate 或 isolated worktree 上执行，并核对候选 SHA/diff。

### 2.14 为过测试提高 baseline/豁免

**坑**：guard 红 -> 改阈值。

**后果**：架构债被合法化。

**替代**：先找出为何红；只有 guard 规则本身被证伪时才修改规则。

### 2.15 多种机制混在一个大提交

**坑**：history、cache、provider、Web、summary、tool schema 一起“顺手优化”。

**后果**：出问题无法归因，也难回滚。

**替代**：一个阶段一个职责；独立 commit + focused gate + scoped diff。

### 2.16 只看配置文件，不看真实 runtime 请求

**坑**：providers.json 改了就宣布生效。

**后果**：进程没 reload、默认覆盖、provider 组装漂移都可能被漏掉。

**替代**：验证配置解析、live process、backend received params 三层。

### 2.17 单-slot 串行被误认为“多 Agent 并发已解决”

**坑**：有一个全局 lock 就认为不会重复。

**后果**：取消/断连/重试后的过期 queued request 仍可能后来执行。

**替代**：并发层用机械 request ownership：`request_id + FIFO + queued/running/cancelled/completed + cancel propagation + idempotency`。不要让程序判断任务语义。

### 2.18 看到“重要/完成/应该总结/应该恢复”就写程序规则

**坑**：为了优化 token/速度，逐渐把语义选择塞回代码。

**后果**：短期指标变好，长期出现健忘、断链、重复、错误恢复。

**替代**：如果一个判断需要理解内容含义，优先交给模型；程序只提供事实和可逆能力。

---

## 3. 标准开发/修复流程

### Step 1 — 锚定现状

- `git status` / branch / HEAD；
- 当前 live process 与端口/后端；
- 当前 provider/runtime 真实参数；
- 当前失败 session/request 的 exact event/payload 事实。

不要从旧经验直接推断当前实现。

### Step 2 — 先把问题分成“模型问题”还是“模型输入/运行环境问题”

优先排查：

1. provider-view 是否包含应有最近上下文；
2. 是否发生 source/projection truncation；
3. role/tool protocol 是否变形；
4. runtime 输出预算/timeout/queue 是否触发机械边界；
5. cache 是否只是性能事实而非内容事实。

只有这些成立后，才讨论模型本身的推理能力。

### Step 3 — 写失败不变量和 RED regression

真实事故应该先变成：

- 一条可以稳定失败的最小测试；
- 一个明确的不变量，例如“最近 3 个完整 dialogue pairs 可见”“exact ref 第二次读取不重复第一页”。

不要先改代码再回头找测试来配实现。

### Step 4 — 最小修复，保持权责边界

修复只解决已证实的机械缺口：

- 丢事实 -> durable exact source/ref；
- 最近连续性丢失 -> mechanical adjacency window；
- provider 参数漂移 -> explicit runtime contract；
- retry 重复 -> request ownership/idempotency；
- 层级错误 -> 调整 ownership/module placement。

不要趁机加入未验证的自动策略。

### Step 5 — Focused gate

至少覆盖：

- 新 regression；
- 相邻 continuity/protocol/storage tests；
- Ruff / type / compile；
- diff-check；
- 隐私/绝对路径/secret scan（涉及公开代码时）。

### Step 6 — Final candidate gate

在 staged candidate 或 isolated worktree 上验证，避免旧 HEAD 假绿：

- full pytest / required CI equivalent；
- architecture ratchets；
- package/build（若相关）；
- scoped diff；
- candidate SHA/changed paths。

### Step 7 — Live qualification（仅需要运行态时）

只重启真正需要重载的组件。前后记录 PID/健康状态，确认未误动邻接 runtime。

验证：

`source config -> runtime resolved config -> actual backend request/receipt`

### Step 8 — 独立提交，阶段冻结

- 一个职责一个 commit；
- 不 push/发布，除非用户明确授权；
- 阶段收口后不要继续“顺手扩大机制”；
- 新问题另起分支/设计/提交边界。

---

## 4. 模型体验异常的优先诊断顺序

当用户反馈“模型突然变差”时，按以下顺序排查，避免误伤已经正常的模型参数：

1. **刚说完就忘** -> 检查 next-turn provider-view/history projection；
2. **重复思考/重复工具** -> 检查 timeout/retry/cancel/queue/request ownership，再查 reasoning replay；
3. **空响应** -> 检查 hidden reasoning 是否耗尽 `max_tokens`、finish_reason、partial checkpoint；
4. **长文找不到** -> 检查 exact source/ref/hydration，而不是加更大 prompt；
5. **摘要与原文不一致** -> 检查 source SHA/coverage，摘要是否只基于 preview；
6. **缓存命中下降** -> 先作为性能/前缀事实分析，不把 cache 状态升级为任务权威；
7. 上述都排除后，才调整模型/sampling/quantization/runtime。

---

## 5. 六问速查卡

开发或修复前，必须能回答：

1. **原文/完整事实源还在吗？**
2. **模型以后能用 stable ref 找到并完整回读吗？**
3. **模型实际 provider-view 里真的看到了我们以为它看到的内容吗？**
4. **参数/行为在当前 runtime 上有真实 qualification 吗？**
5. **程序有没有偷偷接管语义、重要性、完成或恢复判断？**
6. **最终 gate 验证的是 staged/isolated candidate，而不是旧 HEAD、错解释器或管道假绿吗？**

任何一问答不上来：**先取证，再开发。**

---

## 6. Third-party agent quick contract (English)

Before changing or repairing LFL behavior, read this document and follow `RULE-AI-24`.

Six mandatory checks:

1. Preserve the exact source before any projection/truncation.
2. A stored source is not recoverable until the model has a stable, authorized exact-read path.
3. Diagnose the actual provider-visible input before blaming model capability.
4. Qualify runtime parameters on the current backend; never copy another backend's defaults as parity facts.
5. Keep semantic judgment with the model; code owns facts, hard boundaries, lifecycle and recoverability.
6. Run final gates against the actual staged/isolated candidate, not a stale HEAD or the wrong interpreter.

A real incident is not closed until it has a regression test. A summary never outranks its exact source. A successful stage should be frozen as an independent commit instead of becoming a vehicle for unrelated optimizations.

---

## 7. 事故证据与对应修复

以下提交是本手册的直接事故证据，供考古与回归定位；它们不是当前任务授权：

- `8a45047` — preserve model capability contracts；跨 runtime output budget / reasoning replay / runtime identity；
- `9766aee` — recent dialogue working set；修复刚讨论完即丢最近语境；
- `47556cb` — preserve exact truncated sources；capture 与 replay 解耦；
- `957b417` — exact attachment / parent source hydration；第二次显式读取不重复展示截断；
- `deea2b5` — model-authored source synopsis；摘要绑定 exact source，WorkingState producer 继续 HOLD。

本机运行态 experience store 可额外保留事故证据，但仓库级权威只认本手册与 `RULE-AI-24`，避免 ignored/private 经验文件成为 fresh-clone 依赖。
