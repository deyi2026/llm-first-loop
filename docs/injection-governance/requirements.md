# 注入治理专项（INJECTION-GOVERNANCE）需求规格

> 立项: GOAL-20260829-afd095ab | 2026-08-30 | 状态: **设计已审批；R0-R8 PASS（R7 exact cognilocal coverage=N/A；R8 shadow PASS / canary NOT READY）；R9 未实施**

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

## 4B. R2 已验收的统一注入预算

- 总预算 SoT：`INJECTION_BUDGET_CHARS`；默认 **8000 仅为候选值**，R7/L3 A/B 前不得宣称最佳/最终。
- 最小运行值 512 字符，用于保证超限时仍可在同一预算内携带一条非祈使组装回执。
- 中央 assembler 同时收集：history 已持久化 program-origin、本轮动态 slots、enforce packet/header；Cognitive=off 且无新 slots 也不能绕过。
- 裁决粒度是完整 block：只保留或整块丢弃，R2 自身不做半块截断。
- 统一优先级：预算回执 > 程序恢复 > 关键状态（decision/anchor/frontier/interop/gate）> 其他状态 > reference。
- accounting 对最终渲染采用保守成本估算（含 group/slot/merge 开销），因此 `used_chars <= budget` 是硬门，实际 program-origin wire 字符不高于 accounting。
- `COG_RUNTIME_PACKET_BUDGET` 属 Cognitive 内部投影压缩，只会进一步减少 packet；它不是跨来源注入总预算，也不能扩大 R2 上限。
- R2 不实施 session 去重、K 轮按需、身份剥离、恢复次数策略、user-truth 物理尾位重排；分别留给 R3-R6。

## 4C. R3 已验收的资料按需化 / 指针化 / 去重

权威报告：`docs/injection-governance/r3/report.md`。

- 自动资料窗口由 `REFERENCE_AUTO_TURNS` 控制，默认 3 仍是候选；K+1 默认关闭，显式 task switch 临时重开。
- 每个自动 reference frame 最多两行：一句中性事实 + stable ref；command-shaped 历史不自动内联。
- session seen-set 不新增第二份 Session 状态；从持久 message metadata 的 `reference_key(s)` 重建，stable ID 优先、无 ID 用规范化内容 hash，跨 compact 保持。
- memory / experience / skill / SessionDigest 已按同一策略投影；重复 stable ref 默认零正文，任务切换相关命中最多一行 ref。
- compact/archive 不再自动回灌旧消息片段、`[压缩关键事实]` 或 `[压缩档案目录]`，只保留两行 `ref=archive:search_archive` 状态；原文仍完整可检索。
- hotcard 自动表示降为两行状态 + `ref=file:.../task_hotcard.json`；完整结构可 `read_file`，恢复/消费语义未提前进入 R4。
- 09c44093 x18 重复 trap：同一 `memory:m1` 连续命中 18 次，完整正文只注入一次。
- adversarial hardening：human user 中的 `ref=` 不得污染 seen-set；`memory:<id>` / `experience:<id>` / digest archive ref 必须能由对应检索路径精确水合；keyword/semantic memory 检索都在候选层保持 session scope；真实 SessionStore restart 后 seen-set 仍成立。
- R3 暴露并修复了旧 compact anchor 伪 PASS：真实 user anchor 现在保留原消息本体，而不是归档后靠 `[压缩关键事实]` 字符串 echo 假装仍在。
- 原 R3 focused 237 tests PASS；post-R3 adversarial audit 扩展为 281/281 PASS；R2 15 点预算矩阵继续满足 `actual <= used <= budget`；R0 frozen 0-byte diff。

R3 **没有**实现恢复单边界、身份问答剥离、user-truth 物理尾位 / provider wire invariant 或行为 A/B。

## 4D. R6 已验收的 User Truth Tail / Wire Invariant

权威报告：`docs/injection-governance/r6/report.md`。

- initial human-ingress provider view 有 program 时必须是单 user envelope：`program appendix → fixed separator → exact user truth`；无 program 正常请求保持 byte-identical no-op。
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

权威报告：`docs/injection-governance/r7/report.md`。

- A 臂确定性重放 R0 的 post-user / duplicate / imperative reference / identity-attraction 结构；B 臂直接使用 production R2/R3/R5/R6 helper，排除工具与网络成功率变量。
- `qwen3.8-27b-mlx@4bit`：A completion=66.67%、dominance=0%、injection=32.57%、structure FAIL；B completion=100%、drift=0%、dominance=100%、injection=16.44%、structure PASS。
- `qwen/qwen3.8-27b` 对照 A/B 均 completion=100%，但 A 仍 structure FAIL；B structure PASS 且 injection 32.57%→16.44%。
- B 结构硬门：post-user=0、完整重复=0、reference imperative=0、tail_user_run<=1、exact user suffix=true。
- 校准：K=3 是 [0,1,3] 中唯一保住 critical T6 的候选；budget=900 是 [512,900,2000,8000] 中最小通过候选。生产默认 8000 在 R7 不变。
- 原指定 `cognilocal/qwen3.8-27b-cog` 本轮 8901 不提供，覆盖=N/A；未以其它模型冒充。

## 4G. R8 已验收的模型能力分档 Shadow

权威报告：`docs/injection-governance/r8/report.md`。

- 能力事实只取当前路由所绑定的 `ProviderRegistry/ModelSpec` 快照；不按模型名、provider 名、context、价格或 thinking 状态猜档。
- 沿用既有 `capability_tier=strong/weak/unknown`，不新增第二套 tier 枚举：`weak/unknown -> minimal`；`strong + reasoning=false -> standard`；`strong + reasoning=true -> full`。`unknown` 继续遵守既有“保守视为弱”契约。
- R8 第一阶段固定 `mode=shadow`、`applied=false`，推荐值不得进入 build、R2 budget、R3 K/seen-set、R4 recovery、R6 provider-view projection 或 provider payload。
- 归因采用独立 `injection.profile.shadow` 事件而不改写 `request.meta`：primary、每个真实 fallback provider call、err1210 blind/strip retry 均逐 attempt 记录；resolve 失败不冒充 provider attempt。
- capability-only A/B 证明：同 model id / system / tools / user，只改能力元数据使推荐从 minimal 变 full，实际 provider `messages + tools` 序列化结果 byte-identical。
- R8 初验时运行时 inventory 为 11/11 `unknown -> minimal`、覆盖 0%。Post-R8 R8.1 只对有受控证据的模型补 metadata；随后 owner 退役不用的 Qwen3.6，R8.2 远端受控 A/B 后当前为 9/10 已分类：strong=1、weak=8、unknown=1，classified/metadata-complete coverage=90.0%，profile full=1/minimal=9，`canary_ready=false`；唯一 unknown 为持续 HTTP 502 的 `mxnook/glm-5.3-flash`，不得把 transport failure 猜成 weak。
- R2×R4×R5×R6 正交矩阵 15/15 PASS；R0 frozen 0-byte；R8/adjacent focused 268/268 PASS（另 4 个 Web/飞书 model-attribution 用例因当前解释器缺 `pypdf` / `lark_oapi` 未纳入，不是 R8 逻辑失败）；touched production + R8 tests pyright 0/0。

R8 **没有**启用任何 profile 行为。R8 初验未修改 `data/providers.json`；随后 R8.1 做了可逆 metadata-only 文件更新，但未热重载 live registry。进入行为 canary 前仍必须把 capability metadata 补齐并审核到 100%。

## 5. 非目标

- 不修改 LLM 本体。
- 不追求“所有程序信息为零”；必要 system notice 可保留，但不得冒充 user truth，也不得破坏稳定前缀/provider 协议。
- 不把强模型排除在结构治理之外；**行为 A/B 重点是弱模型，wire invariant 则跨模型强制**。
- 不让 `err1210.py` 承担正常注入排序/合并职责。
- 不在本专项处理 REASONING_TAIL 思维链回传。
