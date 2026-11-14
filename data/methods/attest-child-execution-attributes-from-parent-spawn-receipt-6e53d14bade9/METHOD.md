---
method_id: attest-child-execution-attributes-from-parent-spawn-receipt-6e53d14bade9
name: attest-child-execution-attributes-from-parent-spawn-receipt
description: 验收条件要求证明子代理的实际执行属性（用了哪个模型、工具面是什么）时，权威证据在执行 spawn 的那一层：父侧 spawn/topology 运行时回执。child 自检工具返回确定性 unknown/归属不可用是终态回执，重问只会复述同一结果；应在父层直接闭合该属性并如实披露自检状态为非证明，把续话/轮次预算只留给真正的内容缺口。本集 followup 中夹带的 model_catalog 复调即属无信息重复，续话本可单目的化。
aliases: 子代理查不到自己模型怎么算证据, 如何证明child真的用了指定模型, spawn回执能不能当模型使用证据, 模型归属不可用还要不要再问一次, child自检unknown算审查失败吗
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fcd2b1ec-080c-4574-ad69-ff5437a20a7a:0:e2b3146b11a40a36c9ac
evidence_refs: learning:learn:f4612b8be479
created_at: 2026-11-13T18:48:09.058703+08:00
updated_at: 2026-11-13T18:48:09.058703+08:00
---
## Trigger
委派验收清单含『证明 child 实际执行属性（模型/工具面/身份）』类条件，child 已 terminal=completed 但其自检回执为确定性『unknown/归属不可用』，父侧 spawn/topology 回执已运行时确认该属性，正要决定是否把该属性交给续话或重问闭合

## Discriminator
两条事实已在手即可定案：① child 自检回执是确定性状态（unknown/归属不可用，非超时、非截断、非瞬态错误）；② 父侧 spawn 回执已含运行时确认的 model/tool_scope 字段。二者并存时，对同一自检工具的任何重问都不可能产生新信息

## Short path
- 把验收条件拆成『执行属性证明』（模型/工具面/身份）与『内容结论』（findings/等价性）两类，各自指派证据权威源：前者=父侧运行时回执，后者=child 的 file:line 证据链
- 执行属性在父层定案：引用 spawn/topology 回执原文，child 自检状态如实披露为『非正向证明亦非反证』，不再交回 child 复查
- 续话/补证只承载内容缺口且单目的（本集：仅读 resolver.py:701-717 及调用点闭①的等价性），不夹带已知无信息的复查项
- 最终报告中属性证据可回溯到回执原文；对内容结论的决定性引用做只读 spot-check 后收口

## Stop conditions
- 执行属性已由父侧运行时回执命名、child 自检状态已披露，且内容缺口全部闭合并经 spot-check
- child 自检给出与父侧回执冲突的具体正向标识（如不同的模型名）→ 停止择一认定，把冲突作为独立 finding 上报
- 自检回执为瞬态（超时/截断）且尚未有过一次有界重试 → 不适用本规则，先重试一次

## Verification
- 最终报告的 model/tool_scope 结论逐字对应父侧回执原文，child 自检被明确标注为非证明性披露
- 全程没有对已返回确定性 unavailable 的同一自检工具发起无新假设的重复调用
- 续话请求中每一项都对应一个仍开放的未知量，删掉任何一项后无信息损失

## Counterexamples
- 运行时存在 mid-run 模型回退或代理改写：spawn 回执只证明路由请求、不证明实际服务模型，此时需换用 child 侧行为/能力探针，而非重问同一 catalog，也不应只信父侧回执
- 合同明确要求 child 带内自证（第三方审计、防父侧单点伪造）：父侧回执不构成充分证据
- unknown 是超时或列表截断等瞬态回执：一次有界重试是有信息的，提前放弃反而错
- child 为跨会话收养、本会话无 spawn 回执：child 自检可能是唯一来源，不能以父层闭合为由丢弃
