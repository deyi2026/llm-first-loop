# 注入治理专项（INJECTION-GOVERNANCE）需求规格

> 立项: GOAL-20260829-afd095ab | 2026-08-30 | 状态: **设计已审批；R0 PASS；R1/L1 PASS；R2/L2-1 PASS；R3+ 未实施**

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
- **R7 模型分档（后置）**：基于 capability 计算 minimal/standard/full，先 shadow；弱模型可零自动资料正文，但所有档位共享同一结构 invariant。
- **R8 A/B 验证**：弱模型是行为改善主验证对象；结构硬门适用于所有 provider/model，包括 GLM。

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

## 5. 非目标

- 不修改 LLM 本体。
- 不追求“所有程序信息为零”；必要 system notice 可保留，但不得冒充 user truth，也不得破坏稳定前缀/provider 协议。
- 不把强模型排除在结构治理之外；**行为 A/B 重点是弱模型，wire invariant 则跨模型强制**。
- 不让 `err1210.py` 承担正常注入排序/合并职责。
- 不在本专项处理 REASONING_TAIL 思维链回传。
