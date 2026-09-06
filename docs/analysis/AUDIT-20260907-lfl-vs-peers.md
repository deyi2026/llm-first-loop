# 审计报告 v2：llm-first-loop 与同类 Agent Runtime 的定位差异、连续性边界与下一阶段路线
- 日期：2026-09-07
- 方法：本地仓库实证（路径/行数/记录）+ 官方文档网络取证（2026-09-06~07 抓取），非清单式比较
- 状态：v2；本地代码事实已于 2026-09-07 复核。外部竞品事实仍按 2026-09-06~07 取证快照处理，未在本轮逐项重抓官方来源的条目标为“外部未复核”，不得当作 hard evidence。

## 结论速览
| 维度 | llm-first-loop | pi.dev | OpenHands | Letta | LangGraph | SWE-rex |
|---|---|---|---|---|---|---|
| 形态 | LFL 理念+超集实现（harness 内核+外层治理/记忆/评测） | 极简 harness 反示范 | 生产级全栈 agent 平台 | agent OS（记忆为核心） | 图编排框架 | SWE 官方评测 harness |
| 主张 | 程序承担执行/持久化/协议/事实与不可替代硬边界；LLM 承担理解/取舍/策略/语义判断/完成裁决 | 极简 harness + extension | 产品化+生态 | 记忆即系统边界 | 控制流代码化 | 官方判定基准 |
| 对 LFL 的启示 | — | harness 最小主义、代码即上下文 | 部署/评测栈工程化 | 记忆体系化是独立层 | checkpointer/断点恢复 | 判定严格性、诚实边界 |

## 一、实证盘点（本地）
- `src/llm_loop` 26 个子包、约 7.5 万行（core 19.3K / tools 9.3K / memory 4.7K / web 4.8K），tests 460 文件，scripts 34 个
- `AGENTS.md` 双区结构（主区+镜像区），上下文治理文档化
- SWE-bench 官方 harness：114 实例 9 批次 resolved 92.1%（docs/analysis/SWE-bench-official-summary_20260818.md），含诚实声明（重依赖仓库未跑）
- 自评记录 5 条（2026-08-20，EVAL-*），上下文健康审查（docs/context_health_review_2026-08-31.md）
- 已知风险：当前仓库根目录实测有 23 个 `.env.bak*` 本地备份；它们被 Git ignore，当前及 Git 历史未发现这些备份进入版本库。应定义为高优先级本地 secret-sprawl / 凭据卫生风险，而不是“已确认泄密”。ROADMAP-B 部分未结。

### 1.1 当前 continuity 实证边界（2026-09-07 本地复核）
- `LFL_TOOL_WORKING_SET_RECEIPTS` 默认关闭；receipt 只做 representation/provenance，不做 relevance/importance/sufficiency 判断。
- selective evidence shadow、working-state checkpoint 的 consumer/persistence/provider projection 已存在；但 `build_working_state_checkpoint()` 在 `src/` 内没有生产 producer 调用，当前仅定义、测试和 benchmark 使用。**S1 production producer 是当前最大单点缺口。**
- provider truncation continuity 已能持久化 exact partial assistant output，并向下一次 provider view 暴露“上次被 provider 截断”的运行事实，不注入“继续”等程序指令。
- private handoff 明确是 historical evidence，不自动获得 current instruction authority。
- SubAgent child session 本身已经经 `SessionStore`/event-log 路径持久化；真正缺失的是进程重启后的 runner topology/ownership 恢复：parent↔child 映射、mailbox、pending handle、terminal/settled state 仍主要是进程内状态。

## 二、逐项对照
### 2.1 pi.dev（badlogic/Mario Zechner）
- 取证：pi.dev、pi-mono 仓库（2026-09-06）
- 核心：模型即 loop，代码即上下文，~10K 行级最小 harness；反对过度抽象
- 差异：LFL 是"理念+超集"，pi 是"理念+最小实现"；LFL 的治理层（goal/task/evidence/审计）在 pi 中不存在
- 启示：harness 内核保持小；实验放 examples 而非框架；代码即上下文降低工具描述负担

### 2.2 OpenHands（原 OpenDevin）
- 取证：github.com/All-Hands-AI/OpenHands、docs（2026-09-06）
- 核心：事件流架构、Sandbox 运行时、评测栈（SWE-bench/MintBench）、云产品（oden、OpenHands Cloud）
- 差异：OpenHands 面向"软件工程 agent 产品"；LFL 面向"通用 agent loop + 程序化共担复杂度"
- 启示：评测驱动可信度（官方 harness 对齐）；Docker 沙箱与事件流是生产化标配

### 2.3 Letta（原 MemGPT）
- 取证：github.com/letta-ai/letta、docs（2026-09-06）
- 核心：agent 内 OS——分层记忆（core/archival/recall）、自编辑记忆、memory blocks、sleep-time agents
- 差异：Letta 记忆是一等公民且围绕 LLM 自治编辑；LFL 记忆与证据/EvidenceRef 绑定，偏审计可恢复
- 启示：memory blocks 的 token 预算化、sleep-time 后台整理，可与 LFL 的 evidence 生命周期互补

### 2.4 LangGraph
- 取证：langchain-ai.github.io/langgraph（2026-09-06）
- 核心：状态机/图编排，checkpointer（持久化+时间旅行）、human-in-the-loop、subgraphs
- 差异：LangGraph 是库/框架，控制流显式在图中；LFL 控制流在 loop 代码+运行时策略
- 启示：checkpointer 的 thread 级恢复模型；图抽象适合确定性流程，LFL 保持 loop 灵活性是对的

### 2.5 SWE-bench / SWE-rex
- 取证：swebench.com、SWE-bench 2025 进展（SWE-rex runtime、CLI、Pro/Business 榜单）（2026-09-07）
- 核心：官方 resolved 判定（F2P/P2P 全过+patch 可应用）、SWE-rex 轻量执行层、Pro 用互联网任务
- 差异：LFL 把官方判定做进自己的评测层而非改判定标准
- 启示：诚实边界——LFL 92.1% 是 114 实例非全量 500，重仓库未跑，报告已自声明；对齐榜单需补重仓库

### 2.6 agent memory 生态（Mem0/Zep/综述）
- 取证：知乎长文《Agent Memory 综述》、Mem0、Zep 文档（2026-09-07）
- 核心：记忆研究焦点在"如何记忆/遗忘/组织"；Zep 时间线图记忆、Mem0 分层 pipeline
- 差异：LFL 强项在"证据链与可恢复"（EvidenceRef/事件流），弱在记忆整理自动化（sleep-time 类）
- 启示：引入时间感知与自动巩固，但须保持可审计性优先

## 三、定位差异本质（三个不可回避问题）
1. LFL 不是 pi 的"又一个 harness"：更准确的边界不是“pi 让 LLM 承担全部”，而是 pi 选择极简核心并把大量能力外置到 extension；LFL 的差异是把执行真相、证据、恢复、授权与审计做成显式 runtime contract，同时坚持程序不夺取语义判断权。
2. 相对 OpenHands/Letta 的真实边界：工程完成度与生态差距客观存在（沙箱/云端/社区）。LFL 更值得形成的差异不是某次本地 KV 命中率，而是闭环证据链 + authority boundary + long-horizon continuity：历史可恢复，但历史不会自动取得当前任务权威。
3. 相对 LangGraph：图编排把不确定性挤出主流程；LFL 保留不确定性但用程序化护栏约束。选择取决于任务可图化程度

## 四、风险与行动项（v2 优先级）
| 风险 | 证据 | 建议 | 优先级 |
|---|---|---|---|
| 本地 secret sprawl | 根目录 23 个 `.env.bak*`；均被 ignore，Git 当前/历史未发现被跟踪 | 先做不输出秘密值的 credential inventory；清理明文备份；仅对仍有效或无法排除外传的凭据执行轮换 | P0-hygiene |
| S1 生产链缺口 | `build_working_state_checkpoint()` 在 `src` 无生产 producer | 先实现 model-selected Evidence IDs + model-authored working state 的生产 producer；程序只做机械 schema/digest/bound 校验 | P0 |
| continuity 概念重叠 | receipt / selective evidence / working-state / recent continuity / truncation / handoff 并存 | 收敛成 Continuity Kernel 1.0，明确每种状态的 owner、生命周期、失效条件与恢复路径 | P0 |
| SubAgent 重启不可恢复 | child Session 已持久化，但 topology/mailbox/handle/ownership 为进程态 | 不新建第二持久层；基于 SessionStore/EventLog 补 topology replay + generation/lease ownership，防双执行 | P1 |
| 评测外推过度 | 114/500，重仓库未跑 | 补 django/sympy 重仓库批次，公开样本构成 | P1 |
| Execution boundary 分散 | 工具各自承载部分环境/权限语义 | Continuity Kernel 收敛后，再统一 local/container/remote 与 filesystem/network/credential/deployment capability boundary | P2 |
| 记忆整理自动化落后于 Letta/Zep | 对比 2.3/2.6 | 后置；采用带 provenance/version/revert 的 proposed diff，而非自动获得 prompt authority | P2 |
| harness 膨胀 | 7.5 万行 vs pi 1 万行 | 定期"内核最小性"审查（AGENTS.md 已有约束） | P2 |
| ROADMAP-B 未结项 | docs/ROADMAP-B-20260814.md | 逐项结清或显式废止 | P2 |

## 五、下一阶段路线：Continuity Kernel 1.0
严格串行，不并行扩功能：

1. **CK0 — clean/green baseline**：先收口当前独立 dirty patch，保证后续 A/B 有可信基线。
2. **CK1 — S1 production producer**：模型看到机械 candidate Evidence catalog；模型返回 selected Evidence IDs + 短 working state。程序只验证格式、digest、范围、finish reason，不判断 relevance/importance/sufficiency。
3. **CK2 — deterministic + real long-agent A/B**：先测 LFL 自身 receipts off/on、S1 off/on；指标至少包括完成率、重复工具调用、Evidence re-read、fold/restart 后重调查率、TTFT/prefill、cache prefix retention、final fidelity。
4. **CK3 — responsibility inventory**：把 RAW EVIDENCE → EXPOSED RAW → RECEIPT → MODEL-SELECTED RAW → WORKING STATE → RESOLVED/RETIRED 的 owner 和状态迁移统一，禁止再增加平行 summary/checkpoint 表示。
5. **CK4 — default-on 裁决**：只有 CK2 证明收益且 CK3 owner 唯一后，才讨论 receipts/S1 默认开启；S2/S3 在此之前冻结。
6. **CK5 — Durable SubAgent Topology Recovery**：复用既有 child Session/EventLog，只持久化可重放机械事实；通过 owner generation/lease 防止旧 worker + 新 worker 双执行。
7. **CK6 — ExecutionWorkspace / Capability Boundary**：在 continuity 内核稳定后再做，不与 CK1~CK5 并行。
8. **CK7 — Memory maintenance**：借鉴 sleep-time/dreaming 仅作为后台 proposed diff；历史记忆仍需 provenance/currentness，不能自动成为当前指令。
9. **CK8 — 横向 benchmark**：最后再投入 Codex/Claude Code/Gemini CLI 等跨 harness 高成本对比；先证明 LFL 自身机制有因果收益。

### 明确不做
- 不在 S1 producer + 真实 A/B 前推进 S2/S3 selective evidence。
- 不新增第二套 summary/checkpoint/working-state 表示。
- 不让程序判断 Evidence 的 relevance、importance、sufficiency 或 task applicability。
- 不把 Letta 式 memory consolidation 自动注入普通 prompt。
- 不在 durable recovery 前继续扩 SubAgent 类型/编排复杂度。
- 不把 continuity runtime fact 写成“继续/必须执行下一步”等程序指令。

## 六、定位建议
LFL 不应定位成“另一个 coding agent/harness”，更合适的是：

> **Auditable long-horizon LLM-first agent runtime**  
> 程序保存、执行并呈现真实状态；历史与证据可恢复、可审计，但不会自动获得当前任务权威；模型保留语义判断和策略裁决权。

这也是当前最有辨识度、且能由本地实现事实支撑的竞争优势。

## 七、取证索引
- 本地：src/llm_loop（26 包）、docs/analysis/SWE-bench-official-summary_20260818.md、docs/ROADMAP-B-20260814.md、docs/context_health_review_2026-08-31.md、docs/DESIGN-20260903-llm-agency-first-repair-optimization.md、docs/ANALYSIS-20260831-model-agency-obstruction-audit.md、CHANGELOG.md（M61）
- 外部（2026-09-06/07 抓取）：pi.dev；github.com/badlogic/pi-mono；github.com/All-Hands-AI/OpenHands；OpenHands docs；github.com/letta-ai/letta；Letta docs；langchain-ai.github.io/langgraph；swebench.com（含 SWE-rex/Pro 页）；Mem0 docs；Zep docs；知乎 Agent Memory 综述
- 会话证据：web_search/web_fetch 的 EvidenceRef 存于本会话 Evidence 库（关键词：pi-mono、OpenHands、letta memory blocks、swebench swe-rex、zep temporal knowledge graph）
