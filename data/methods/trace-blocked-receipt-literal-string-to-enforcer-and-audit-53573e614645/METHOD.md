---
method_id: trace-blocked-receipt-literal-string-to-enforcer-and-audit-53573e614645
name: trace-blocked-receipt-literal-string-to-enforcer-and-audit
description: 用户问"是什么隔离/限制了这些操作"且会话内已有对应失败回执时，把回执中的字面 reason/规则编号当作 provenance 边：用该精确字符串搜索执行源码定位限制者实现与触发条件，再读专用审计日志取历史。不要在只收录 success 的 evidence 库上换关键词反复搜，不要 hydrate 无关成功回执，也不要追 llm_error 等基础设施噪音分支。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f88bda21-3714-409e-a903-eeb08b562780:277:580f9fcba4bddcef61cd
evidence_refs: learning:learn:7e551f1995af
created_at: 2026-09-23T09:15:50.958221+00:00
updated_at: 2026-09-23T09:15:50.958221+00:00
---
## Trigger
用户询问某些操作被什么机制限制/阻断/隔离/拒绝，且会话 transcript 中已存在这些操作的失败回执，回执含稳定可检索的 reason 字符串或规则 id。

## Discriminator
会话内失败回执已给出字面 reason（如"已硬阻断（FR-SAFE-01）"）；同时 evidence 库条目 provenance.scope=success，结构性缺失失败/阻断数据——在 evidence 上换关键词搜索必然为空，权威记录只存在于执行源码与审计/异常日志通道。

## Short path
- 在 transcript 中对准用户所指操作，定位其失败回执，取出字面 reason/规则 id——未知量：限制机制叫什么、由谁执行
- 用该字面串对代码库做精确 search_files——未知量：哪个模块产生这条 reason、规则逻辑是什么
- 读命中处的源码区域（含设计注释与判定链）——未知量：为什么本次命中、设计边界与预期出路
- 如需历史/次数，对专用审计日志（如 audit/safety_blocks 类文件）做一次 tail/解析——未知量：该机制的历史行为
- 汇总机制名+本次命中规则+判定链+审计佐证，回答并停止

## Stop conditions
- 执行源码中的 reason 模板与回执字面串逐字一致，且审计日志存在与本次时间戳/命令对应的记录
- transcript 中找不到用户所指操作的失败回执——转向向用户澄清指代，或进入目录/日志层 broad discovery

## Verification
- 源码命中的 reason 字符串与回执原文完全匹配（非近似关键词）
- 审计日志记录的时间戳、命令与本次被拦操作一致
- 结论不依赖 evidence 关键词搜索结果（其 scope=success 天然不含失败数据）

## Counterexamples
- 回执是瞬态基础设施错误（如上游 HTTP 500 网络错误），无稳定代码级字符串——精确搜索找不到"限制者"，答案在运维层面而非源码
- 阻断发生后源码已修改，当前实现≠当时触发的规则版本——应以审计日志快照为准而非现读源码
- reason 是泛化模板且命中多个模块——需先按工具名/规则 id 收窄再读码
- 用户所指操作从未在本会话发生（无回执可循）——必须澄清或宽搜索，本方法不适用
