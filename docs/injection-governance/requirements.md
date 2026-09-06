# 注入治理专项（INJECTION-GOVERNANCE）需求规格

> 立项: GOAL-20260829-afd095ab | 2026-08-30 | 状态: **设计已审批；R0-R8 PASS（R7 exact cognilocal coverage=N/A；R8 shadow PASS / R8.3 SOAK PASS / behavior canary NOT STARTED）；R9 未实施**

## 1. 问题陈述（实证）

**P1 用户真话与程序附录同属 user 角色且程序块位于其后**：模型必须靠自然语言标记判断归属；弱模型更容易把结尾程序块当成当前任务。

**P2 资料块含命令式语言**：历史 memory/experience 中存在“继续当前任务 / 勿当新指令 / 必须调用 / 应调用”等 command-shaped 文案，与真实用户指令同级竞争。

**P3 长会话重复放大**：同一事实帧可反复进入上下文；重复本身会被模型当成重要性信号，且旧“最近 N 条”去重无法跨长会话/compact 阻断。

**P4 注入密度过高**：历史样本中 program appendix 可远大于用户真话；预算只是上限，不等于资料压缩/指针化。

**P5 provider wire 结构风险**：程序附录/compact 等组合可产生连续 user-role 消息；GLM 已有 HTTP 400/1210 结构敏感实证，正常 wire 必须在首次 HTTP 前满足 provider invariant，而不是交给 err1210 recovery 兜底。

## 2. 核心原则

1. **用户真实指令 > 一切程序注入**；冲突时必须有唯一仲裁规则。
2. **结构他律 > 标记自律**：能从结构上消失/降密/去重的问题，不依赖模型“读懂提示”。
3. **资料不是命令**：memory/experience/archive 只提供陈述事实与 ref。
4. **用户原话语义尾位**：program appendix 在前、用户原文在最后；同时服从 system/tool/provider wire 协议。
5. **可证伪**：结构硬门用确定性 fixture，行为改善用 L3 A/B，二者不混淆。

## 3. 需求清单

- **R0 数据门**：离线重建 user truth/program appendix/system notice；记录 `user_truth_chars / injection_chars / injection_after_user_chars / duplicate / imperative / model / compact / recovery / wire user-run`；冻结 baseline + manifest + redacted fixtures。
- **R1 语义边界**：四层语义标签；program appendix 顶部唯一优先级声明；资料块禁用祈使句。
- **R2 预算门闸**：注入总预算由统一 assembler 强制；整块按优先级丢弃并给非祈使回执；8000 仅为候选值。
- **R3 按需 + 指针 + 去重**：资料正文不再每轮投喂；每帧 ≤2 行（事实 + ref）；session-scoped seen-set 跨 compact 保持，同一事实完整正文每 session 最多一次。
- **R4 程序恢复边界**：auto_continue/recovery 明示“程序恢复、非用户新指令”，只允许一个确定动作。
- **R5 身份问答剥离**：identity Q&A 不进入长期摘要细节。
- **R6 user truth 尾位 / wire invariant**：任何 program-user 不得落在本轮用户原文之后；需要同为 user 角色时组装为单 envelope；GLM `tail_user_run<=1`，tool pairing/system 位置同时合法。
- **R7 A/B 验证**：弱模型是行为改善主验证对象；结构硬门适用于所有 provider/model，包括 GLM。
- **R8 模型分档（后置）**：基于 provider capability 单一来源计算 minimal/standard/full，第一阶段仅 shadow；所有档位共享同一预算/去重/尾位/wire invariant。

## 4. R0 已冻结的事实基线

权威报告：`docs/injection-governance/r0/report.md`。R0 只做确定性离线分析，不重新调用模型。

- origin classification coverage = 100%；request-bearing turn attribution coverage = 100%。
- user-role program appendix 位于用户真话之后的 completed turn = 71/170（41.76%）。
- reference frame duplicate = 340/666（51.05%）。
- reference imperative = 23/666（3.45%）；user-role program block 命令式 wrapper = 172/173（99.42%）。
- observed wire tail consecutive-user violations = 133/707（18.81%）。
- clean control `69715765`：user-role injection=0、尾后注入=0、reference duplicate=0、wire tail violation=0。

以上数字由事件日志 SHA 固化，完整 provenance 见 `baseline-manifest.json`。

## 4A. R1 已验收的语义边界

权威报告：`docs/injection-governance/r1/report.md`。

- `injection_labels.py` 为四层语义与 program appendix 仲裁声明的单一真相源。
- 用户正文保持逐字，不用可见前缀改写；USER_INSTRUCTION 通过 origin metadata 标识。
- program-user 不再靠 `role=user` 冒充人类来源；memory/experience/model-switch/declaration/recovery 均有 canonical origin metadata。
- REFERENCE 自动资料中的 command-shaped 历史正文不自动内联，只给中性占位 + ref；原文仍可检索。
- build/Cognitive 聚合 appendix 的仲裁声明在 production enforce fixture 中严格为 1 条；尾部 program appendix 不再被 cognitive cache tag 误识别为 `goal`。
- focused unit/integration 147 tests PASS；R0 frozen baseline 重放无 diff。

R1 **没有**实现预算、按需/去重、恢复单边界、身份剥离、user truth 物理尾位或行为 A/B。

## 4A-1. P1-C 当前 Prompt Authority 契约（2026-09-04）

- 自动 program prompt producer registry 为空；unknown/unapproved producer fail-closed to retrieval/tool/event plane。
- 不存在 runtime Injection Profile 或 semantic Injection Budget；model capability tier、program block kind/priority 不得决定 prompt density/keep/drop。
- historical `injection.profile.shadow` event schema 只为旧 append-only log 兼容，不得再有新 emitter。
- physical provider context limit、history byte/token capacity、output reserve、overflow retry/termination、compaction 属机械资源边界，继续保留。
- Cognitive state/packet 若保留，只能 prompt-neutral observability，不能以 packet/profile/budget 名义恢复 program prompt authority。

## 4B. R2/R3 历史注入控制面（已退役）

> **当前权威（2026-09-06）：**R2 `INJECTION_BUDGET_CHARS`、R3
> `REFERENCE_AUTO_TURNS` / task-switch / seen-set / automatic reference frame、以及
> Cognitive packet/tier 均只保留历史证据，不再是生产契约。

- dynamic program prompt producer registry 必须为空；程序不得通过自动 memory/reference/
  experience/digest catalog 获得 prompt-write 权限。
- persisted legacy program frames 允许被机械识别并从 provider view scrub，但该兼容逻辑不能
  产生新正文。
- memory / experience / archive 通过 stable ref + explicit retrieval/exact hydration 提供；
  程序只给 provenance/currentness 等机械事实，`task_applicability=not_evaluated`。
- compaction/folding 仅在实际 routed-model 物理窗口或显式 operator cap 触发时做机械表示变换；
  不按语义相关性摘要/裁剪，不自动注入 `[当前决策]`、key facts、目录或“压缩提示”。
- durable archive / EvidenceRef / provider-native replay state 是恢复真相；provider compaction 使用
  versioned marker 防止同一旧 span 每轮重写。
- 历史 R2/R3 设计、A/B 与验收数据仍见 `r2/report.md`、`r3/report.md`、`r7/`，不得据此
  恢复旧生产权力。

## 4D. R6 已验收的 User Truth Tail / Wire Invariant

权威报告：`docs/injection-governance/r6/report.md`。

- initial human-ingress provider view 有 program 时必须是单 user envelope：`program appendix → fixed separator → exact user truth`；无 program 正常请求保持 byte-identical no-op。
- 2026-09-03 复审限定：上述单-user envelope 只是一项 provider/1210 transport 兼容形态，**不是 protocol-level provenance isolation，也不能作为行为治理 PASS 证据**。应优先减少/取消非必要 program-origin prompt material；不得靠可见文字标签要求模型自行恢复来源边界。
- exact user truth 来自 canonical Session current turn，byte-for-byte、不复制、不追加 program suffix；未知第二 human 不得被吞并。
- tool-followup 不重复 user truth，必须保持 assistant/tool pairing。
- compact 不得用摘要/指针/截断文本替换 current human truth；truth 自身超 history budget 时保留原文并由上层 context guard 显式拒绝。
- err1210 USER_ENVELOPE 降级只剥 program prefix，retry 保留 exact human；one-shot program sources 由 sidecar defer。
- R2×R6 15 点矩阵含 fixed separator 后仍 `generated_program_chars <= accounting used <= budget`，且 `tail_user_run=1`。
- 最终扩展回归 413/413 PASS；R0 frozen 0-byte diff；touched production pyright 0/0。

R6 **没有**实施 R4 recovery 单动作策略、R5 identity stripping、R7 A/B 或 R8 model tiering。

## 4E. R4 已验收的程序恢复单边界

权威报告：`docs/injection-governance/r4/report.md`。

- recovery action 使用 closed `ProgramRecoveryAction`，当前唯一动作是 `retry_current_request_once`；调用方不能夹带自由文本扩展任务。
- 可执行 recovery 为 per-session `_RunState` one-shot slot，`recovery_turn_ref` 必须匹配 current human turn；build 读取即清空，不能跨 tool-followup、新用户轮或并发 session 复活。
- pre-R4 persisted recovery 保留 storage/audit truth，但 provider view 永久过滤；真实 `MessageSource.USER` 即使包含 legacy marker 也不得被误判。
- durable audit 由 `program.recovery` event 承载，而非把可执行 recovery 保存为 `message.appended` 对话历史。
- recovery 与其它 program-origin 共用 R2 hard budget；budget 决策后从 Cognitive/background appendix 分离，避免被“仅作背景”声明或 WARM projection 改写，再由 R6 合并到 exact user truth 前。
- 143/143 focused、458/458 expanded、R2×R4×R6 15/15、R0 frozen 0-byte、pyright 0/0 全部 PASS。

R4 **没有**实施 R5 identity stripping、R7 行为 A/B 或 R8 model-tier shadow。

## 4F. R5 已验收的身份问答长期摘要剥离

权威报告：`docs/injection-governance/r5/report.md`。

- R5 不删除用户/assistant/tool 原文，只治理 derived long-term summary/index；raw archive、reasoning 与 Session trim backup 保持可逆。
- active summary surface 经代码审查确定为 ArchiveStore summary/index + legacy Session trim summary JSONL；`fixed_summary/summary_chain` 当前为 inert 兼容字段，R5 不重新激活。
- identity/self-description episode 由 genuine human identity-only turn 开启，跨 program-user/tool/assistant，下一 genuine human turn 关闭；pre-R1 无 metadata program-user 兼容识别，current `origin_layer=user_instruction` 优先于可见 program-like label。
- classifier 采用 whole-turn 保守规则：后续子句若出现独立真实任务则整条保留。冻结 clean-control 的 `你现在是什么模型？上一轮我让你记了什么？` 被正确保留。
- 新 identity archive 的 summary/index 被净化并标记 `summary_source=identity_filtered`；自动 semantic backfill 跳过；`search_archive(with_summary=true)` 不再从 raw preview 二次摘要身份细节。
- Session trim 在一个早期批次内将多个 identity episode 聚合为单行 `[身份问答 x N 轮，已略——本会话主体任务见下]`；非身份摘要零改写。
- 冻结 event-log 审查：68fed5f5/09c44093/996e7e52 各命中 1 个纯 identity opener；69715765 genuine-human=102、identity=0。
- 97/97 focused、542/542 expanded、R2×R4×R5×R6 15/15、R0 frozen 0-byte、pyright 0/0 全部 PASS。
- pre-R5 archive 不做 destructive migration；R3 已停止 archive summary 自动 prompt 回灌，存量只在显式检索时可见。

R5 **没有**实施 R7 行为 A/B、R8 model-tier shadow 或 R9 主区应用。

## 4F. R7 已验收的 L3 A/B

历史报告：`docs/injection-governance/r7/report.md`。**当前裁决以 `docs/injection-governance/r7/CURRENT-STATUS-20260903.md` 为准。**

> 2026-09-03 agency-first 复审：R7-v1 降级为 frozen historical diagnostic；不得再据其 A/B 结果做 model strong/weak、primary admission、fallback floor、injection profile 或 K 默认值裁决。以下数值仅保留历史证据语义。

- A 臂确定性重放 R0 的 post-user / duplicate / imperative reference / identity-attraction 结构；B 臂直接使用 production R2/R3/R5/R6 helper，排除工具与网络成功率变量。
- `qwen3.8-27b-mlx@4bit`：A completion=66.67%、dominance=0%、injection=32.57%、structure FAIL；B completion=100%、drift=0%、dominance=100%、injection=16.44%、structure PASS。
- `qwen/qwen3.8-27b` 对照 A/B 均 completion=100%，但 A 仍 structure FAIL；B structure PASS 且 injection 32.57%→16.44%。
- B 结构硬门：post-user=0、完整重复=0、reference imperative=0、tail_user_run<=1、exact user suffix=true。
- 历史校准曾选 K=3 / budget=900；该结论已于 2026-09-03 失去生产默认值裁决权。T6 是 tool-less synthetic memory dependency，不能证明 blanket auto replay 必要。
- 原指定 `cognilocal/qwen3.8-27b-cog` 本轮 8901 不提供，覆盖=N/A；未以其它模型冒充。

## 4G. R8 已验收的模型能力分档 Shadow（历史；P1-C 已覆盖）

> **当前权威（2026-09-04 P1-C）：**runtime Injection Profile recommendation / emitter 已退役，不再按 capability tier 计算 prompt density，也不再新写 `injection.profile.shadow`。历史 event schema 保留为 append-only 旧日志读取兼容。

权威报告：`docs/injection-governance/r8/report.md`。

- 能力事实只取当前路由所绑定的 `ProviderRegistry/ModelSpec` 快照；不按模型名、provider 名、context、价格或 thinking 状态猜档。
- `capability_tier` 仅保留兼容/审计元数据；R7-v1 不再是 tier 来源。`unknown`=无结论，禁止负面能力推断；只有独立 production-path 证据明确标注的 `weak` 才可被 capability floor 视为低于下限。tier 不再映射注入密度，profile telemetry 统一 neutral `standard`、shadow-only。
- R8 第一阶段固定 `mode=shadow`、`applied=false`，推荐值不得进入 build、R2 budget、R3 K/seen-set、R4 recovery、R6 provider-view projection 或 provider payload。
- 归因采用独立 `injection.profile.shadow` 事件而不改写 `request.meta`：primary、每个真实 fallback provider call、err1210 blind/strip retry 均逐 attempt 记录；resolve 失败不冒充 provider attempt。
- capability-only A/B 证明：同 model id / system / tools / user，只改能力元数据使推荐从 minimal 变 full，实际 provider `messages + tools` 序列化结果 byte-identical。
- 历史 R8.1/R8.2 曾产出 strong/weak inventory 与 profile coverage；2026-09-03 复审确认其强弱来源受 R7-v1 污染韧性测试混杂，active runtime 这些 tier 已撤回 `unknown`。旧 coverage/canary-ready 仅作为历史记录，不再代表当前 admission readiness。
- R2×R4×R5×R6 正交矩阵 15/15 PASS；R0 frozen 0-byte；R8/adjacent focused 268/268 PASS（另 4 个 Web/飞书 model-attribution 用例因当前解释器缺 `pypdf` / `lark_oapi` 未纳入，不是 R8 逻辑失败）；touched production + R8 tests pyright 0/0。
- R8.3 live shadow soak：mirror live registry 已加载 9/9 metadata；strong-short 3 calls、weak-short 3 calls、weak-long-history 1 call，共 `request.usage=7` / `injection.profile.shadow=7`，unattributed=0、profile churn=0、attribution/mode/source violation=0；全部 `mode=shadow, applied=false`。fallback/1210/byte-identity production-path E2E 3/3 PASS；R8.3 + R2/R3/R4/R5/R6 focused 145/145；R0 再次 0-byte。

R8 **没有**启用任何 profile 行为。Metadata gate 与 R8.3 shadow soak 已 PASS，但 behavior canary 仍是独立后续阶段，必须显式批准并使用受控范围/rollback；R9 继续未开始。

## 4H. R8.4 Prompt Eligibility Audit + R8.5 Resolved Episode Retirement

权威审计：`docs/injection-governance/eligibility/audit.md`；机器清单：`docs/injection-governance/eligibility/matrix.json`。

- 新硬原则：**resolved / consumed / superseded / observability 默认不具备 prompt eligibility**；已解决 Q&A、tool chain、reasoning 与旧程序状态应可检索但不自动可见。
- Eligibility 是当前 program-origin 自动 prompt 的最终准入边界；P1-C 后不存在 model profile 或 semantic R2 budget 的后续准入/排序。物理 context/window 资源预算属于另一条机械链路。
- `ACTIVE + REQUIRED_NOW` 才能继续进入 provider context；若程序可自行处理则 0 prompt，若可通过工具/索引按需 hydrate 则默认不内联正文。
- resolved episode 在 provider-view 退休前必须建立 durable index/archive + stable ref + hydration 验证；R8.5 已对**新/proven episode**用独立 `EpisodeStore` 闭合该链路，旧历史没有 resolution proof 时保持可见，不做猜测式迁移。
- durable constraints/decisions 只保留当前 effective state；旧版本标记 superseded 后只留历史检索。
- unknown program producer 默认应 deny；当前 `unknown -> STATUS` 仅满足 R1 语义安全，不满足 Eligibility fail-closed。
- Eligibility gate 必须覆盖普通会话历史、`_inject_parts`、Cognitive `_packet_parts`、Evidence Recovery Manifest 和 tool schemas，不能只治理 canonical injection_kind。
- R8.5 resolution proof 必须强于 `run_end_reason=completed`：仅 non-empty、non-truncated、正常完成的 model answer 可被标为 candidate；durable write 失败、截断、程序回答、legacy 无 proof 一律 fail-open 不退休。
- R8.5 provider retirement 必须同时覆盖 flat history 与 Cognitive packet；resolved memory snapshot 不得从第二条 packet 路径复活。history anchor 必须在原 session index 与 filtered view index 间双向映射，禁止破坏 current user / assistant-tool pairing。
- 明确 cross-turn standing user instruction 必须继续 provider-visible；R8.5 先用保守 lexical guard 保护 exact user 原文，完整 effective-state/supersession store 仍是后续工作。
- retrieval 复用现有 `search_records`，只新增 `kind=episode`；不得为 episode 再新增每轮常驻 tool，且尽量不扩 tool 参数 schema。
- behavior canary P0 前置门仍包括：legacy resolved migration evidence、model-switch 当前轮复制、observability prompt chars、unknown producer eligible=0、Evidence Manifest R2 bypass=0、legacy/unresolved packet memory、round-exhaustion consumed 等。R8.5 PASS **不等于 Eligibility 全部实现**。
- R8.4 权威审计：`eligibility/audit.md`；R8.5 权威实现报告：`eligibility/resolved-episode-report.md`；机器状态只认 `eligibility/matrix.json`。

## 4I. R8.6 Audit + R8.7 Dynamic Tool Eligibility / Recovery

权威审计：`docs/injection-governance/tool-eligibility/audit.md`；机器清单：`tool-eligibility/matrix.json`；恢复规则：`tool-eligibility/recovery-policy.json`。

- 新硬原则：**available is discoverable, not necessarily injectable**。ToolRegistry 中存在的能力默认不因此获得每轮 prompt visibility。
- current runtime config + detached clean-source registry build 为 61 tools；cloud lazy tool-array=22,692 chars。R8.6 建议 universal CORE=9 tools / 3,418 chars，较 clean-source cloud lazy surface 减少 84.9%；其它工具按 task/state eligibility 发现，不等于删除。
- 四态定义：CORE=默认通用；DISCOVERABLE=工具健康但有任务/状态前置；DEGRADED=上下文/域名相关的部分健康能力；QUARANTINED=当前 runtime 确定性前置不满足或 capability=0。
- 当前分类：CORE=9、DISCOVERABLE=49、DEGRADED=1（`web_fetch`）、QUARANTINED=2（`playwright_exec`/`playwright_test`；当前 `.venv` 无 playwright 且 host 无 chromium）。
- 低成功率不得直接等同“坏工具”。必须区分 deterministic environment failure、state/precondition misuse、context/domain mismatch、normal business failure、transient transport failure。
- recovery policy 必须是 failure/context-aware：确定性失败不重复同工具；transient 最多 bounded retry；stale id 不同参重试；schema/precondition 错误先加载 schema/状态；security-policy block 不得自动建议弱化安全边界。
- `web_fetch` 标杆：普通静态站点可继续用；Toutiao 等已知 anti-bot domain preflight 优先 `web-fetch-fast`；403/418/JS-shell 不重复同工具；404 先找 canonical URL；timeout/5xx 才允许一次 bounded retry。
- Skill 本身也受 runtime health：当前 `web-fetch-fast` 的 Chromium 末级 fallback 在本机不可执行，因此实现层必须标出该 fallback unavailable，不能静态照单全收。
- MCP 当前只有 `dsh` server；initialize/tools-list 成功但 tools=0，因此推荐 no-capability quarantine/disable。重入门：`tools/list>0 + schema valid + health probe + allowlist/dedupe review`。
- R8.7 projection 代码保留为显式实验能力，但当前/新部署默认 **`off`**，缺失或非法 mode 也 fail-open 为 off。注册工具的完整可调用面默认交给模型；shadow/enforce 不得因旧模板或局部 fallback 静默复活。
- Hidden healthy tools 不 unregister；`get_tool_schema` 必须提供目录/关键词/exact schema discovery。active assistant-tool protocol 和 typed-recovery-next 必须能把需要的 secondary tool 临时加入 tail。
- QUARANTINED 工具既不能被 prompt projection 暴露，stale direct call 也必须在 execution boundary 被拒绝；Playwright 当前按 Python runtime prerequisite 执行该规则。
- MCP `tools/list=0` 视为 no capability：关闭该次连接、注册0工具；不得仅维持一个“在线但无能力”的 stdio 进程。
- `web_fetch` 是首个 typed recovery SoT：known Toutiao preflight 不执行 generic fetch；403/418/404/429/JS-shell/timeout/5xx/security-block 用结构化 failure class 决定 retry/replacement；matched typed policy 必须替代 generic/experience guidance，避免两套建议。
- R8.6 其它 recovery rules 仍 PROPOSED，不能因 R8.7 `web_fetch` PASS 宣称全部工具恢复策略已实施。Behavior canary / R9 继续冻结。

R8.7 最终硬门：default cloud tool-schema chars <=5,000；universal default tools <=12；hidden-needed discovery fixture=100%；quarantined stale direct execution=0；known deterministic same-tool retries=0；security block unsafe-bypass suggestion=0；tool protocol violation=0；R0 frozen diff=0；detached clean checkout PASS。

## 5. 非目标

- 不修改 LLM 本体。
- 不追求“所有程序信息为零”；必要 system notice 可保留，但不得冒充 user truth，也不得破坏稳定前缀/provider 协议。
- 不按模型名或未经独立验证的 strong/weak 标量施加不同语义治理；模型差异先作为测量维度，不自动获得限制或额外注入。
- 不让 `err1210.py` 承担正常注入排序/合并职责。
- R8.4/R8.5 允许把 historical reasoning 作为 **Prompt Eligibility surface** 治理；R8.5 通过退休 resolved episode 且不复制 `reasoning_content` 来降噪，但不修改 `REASONING_TAIL` 参数或 provider reasoning 协议。
- R8.7 可以改变 prompt-facing tool projection 与 no-capability MCP connection lifetime，但不安装 Playwright/Chromium、不伪造 MCP capability、不删除 healthy discoverable tools，也不进入 model-profile behavior canary/R9。
