---
method_id: failed-row-attribution-triage-before-rerun-63b44d73bd3f
name: failed-row-attribution-triage-before-rerun
description: 当被要求按某个失败归因（如'提供方瞬态'）补跑/修复评测失败行时，先用汇总中已可见的每行终态事实做归因分诊：terminal=completed 且 reward=0 是行为性失败，补跑等于事后选择性替换失败行，统计上不可接受；terminal=provider_error 且 0 轮秒死是提供方侧拒绝，但瞬态/确定性仍需异常原文或载荷-上限反证链才能定。归因之外还须核对协议预注册的补跑规则与指标 n 口径（单臂补 k4 会把 n=3 变 4、破坏冻结构）；若真实意图是裁决臂差，预注册路径通常是双臂对称升级而非单臂补行。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:1354:36c66039dffdb923bbf6
evidence_refs: learning:learn:9decf5808136
created_at: 2026-09-22T16:00:32.216460+00:00
updated_at: 2026-09-22T16:00:32.216460+00:00
---
## Trigger
对失败行提出补跑/重试/修复请求，且请求理由预设了失败原因；或修复动作的正当性取决于失败属于行为性/提供方瞬态/提供方确定性哪一类。多行被同一归因捆绑、而汇总已显示各行终态不同时尤其适用。

## Discriminator
首个汇总/rows 输出中每行的 terminal+rounds+duration 三元组：completed 且 reward=0 → 提供方已正常服务完毕，瞬态归因当场证伪，属行为性失败；provider_error 且 0 轮、秒级死亡 → 提供方侧，但瞬态未证。捆绑多行终态不一致 = 共享归因不成立，必须分行裁决。

## Short path
- 读运行汇总定位全部失败行，记录各行 terminal/rounds/duration/tokens——未知量：每行失败属于哪一类
- 对每个失败行读其自身落盘 row facts（final_answer/usage/checks）——未知量：失败模式是行为退化还是提供方拒绝
- 查驱动与设计文档中失败处理及补跑的预注册规则（是否重试、异常原文是否落盘）——未知量：补跑是否被协议允许
- 查指标聚合代码确认补跑对 n/口径的影响——未知量：k4 是否破坏冻结的 k 结构
- 对归因仍不明的行做同 run 反证比较（同规格成功行、载荷 vs 上下文上限、错误分类函数的覆盖缺口）——未知量：瞬态还是确定性
- 逐行输出归因+协议/口径双层裁决；如意图是裁决臂差，指出预注册内的双臂对称升级路径

## Stop conditions
- 每个失败行已归入行为性/提供方确定性/提供方瞬态之一，且引用该行自身落盘事实（终态、final artifact、tokens），而非仅汇总均值
- 协议预注册规则与指标 n 口径对补跑可否已给出明确判定，裁决可直接导出
- 对无法归因的行（异常原文未落盘）如实标注'不可确证'，不再追加同宽度的确认性读取

## Verification
- 结论逐行给证据：行为性失败引用 terminal=completed+退化产物形态；拒瞬态引用缺异常原文+同 run 反证链（同规格成功行、载荷 vs 上下文上限）
- 拒绝补跑的理由同时覆盖归因与协议/口径两层，而非笼统'不建议'
- 如用户真实意图是裁决臂差，给出预注册内的对称升级路径作为替代方案

## Counterexamples
- 协议已预注册 infra 失败补跑策略（如 provider_error 行补满 k）→ 按协议执行，分诊只用于分类记录，不能否决补跑
- 日志明确是 503/超时且设计允许重试 → 瞬态成立，补跑合理，不可一概拒绝
- 非统计场景的一次性运行（无冻结 k、无臂间比较）→ 直接重跑即可，无需此流程
- rows 落盘缺少 terminal/rounds 字段 → 判别事实不存在，应先修落盘再谈补跑
