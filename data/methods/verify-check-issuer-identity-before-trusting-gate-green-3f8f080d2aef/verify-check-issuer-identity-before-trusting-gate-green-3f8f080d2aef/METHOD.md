---
method_id: verify-check-issuer-identity-before-trusting-gate-green-3f8f080d2aef
name: verify-check-issuer-identity-before-trusting-gate-green
description: required 门禁在 rollup/状态面板显示已满足（SUCCESS、mergeState=CLEAN），而账本已载明其唯一授权签发者是尚未执行动作的特权通道（当前执行面无权 mint）时，这条绿与已核事实直接矛盾，不能当作『已闭环』的重大事实接受。正确动作是一次枚举该 check-runs 的两个可能落点（PR head 与 tested_merge），用身份字段（app_id、external_id 签名格式、绑定 SHA）判别真实签发者 vs 同名占位者：真实签发者有结构化签名前缀并绑定 tested_merge；CI 同名 job 自动创建的占位是 UUID、落 HEAD、app 为 CI 平台自身。结论必须分层：技术上可合并 ≠ 治理闭环。
aliases: 门禁绿了但签发方没动过, 同名CI job占位check冒充通过, check-run external_id验真签发者, mergeState CLEAN但治理未闭环, required check到底谁签的, 占位job满足了branch protection
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:d901b48e-25bf-45f0-a33f-23eaa879ddc3:741:171c9be2c364752f58aa
evidence_refs: learning:learn:aceb0d82b580
created_at: 2026-11-19T09:39:22.564125+08:00
updated_at: 2026-11-19T09:39:22.564125+08:00
---
## Trigger
某 required check/门禁在 rollup 或状态面板显示已满足（如 SUCCESS + mergeState=CLEAN），同时账本/合同记录表明该 check 的授权签发需特权通道执行、当前执行面无权签发、且该通道尚无任何执行回执。

## Discriminator
knowledge-at-time：账本已明确『该门禁只能由 Host 特权通道真实签发、我的通道无权 mint、Host 侧尚未执行』——面板 SUCCESS 与之矛盾 ⇒ 绿必来自另一同名生产者；且真实签发者的身份签名格式与绑定落点已知，可与 check-run 的 app_id/external_id/head_sha 逐字段机械比对。

## Short path
- 未知量=这条绿是谁签的。先读账本/合同：授权签发通道是否已执行、真实签发者的签名格式与绑定落点是什么
- 授权通道未执行 ⇒ 假设同名占位者：一次枚举该名字的 check-runs（head_sha 与 tested_merge 两个落点各查一次；未合并 PR 的预览合并 SHA 用 REST pulls/{n}.merge_commit_sha，GraphQL mergeCommit 为 null）
- 逐字段比对身份：external_id 前缀/结构与真实签发格式 vs UUID 自动格式；app 是否 CI 平台自身；check 落在 HEAD 还是 tested_merge
- grep 工作流文件确认同名 job 占位机制存在（一次定位即成机械证据）
- 分层落结论：占位满足=技术上可合并≠治理闭环，向用户报告真实缺口与剩余特权签发步骤，不自行采信绿

## Stop conditions
- 存在 external_id 匹配真实签发格式且绑定正确 SHA 的 check ⇒ 门禁真实满足，停止探查
- 全部同名 check 均为占位身份（UUID 等自动格式）⇒ 判定门禁未真满足，上报缺口后停止，不再扩大枚举
- 账本/合同表明该 check 的权威生产者就是 CI job 本身（不存在独立特权签发者）⇒ 直接认绿，本方法不启用

## Verification
- external_id 与文档化签名格式逐字段比对（前缀、字段数、pr/候选SHA/testedSHA/digest 绑定）
- 在真实签发者声明的绑定落点（tested_merge）查询该名字 check-runs：结果为空即真签发未发生
- 工作流 grep 命中同名 job 定义，与占位 check 的 app/UUID 身份互证成完整证据链

## Counterexamples
- 合同规定 CI 同名 job 即门禁本体、无更高特权签发者：rollup 绿就是真绿，身份探查属过度怀疑
- tested_merge 上已存在结构化签名格式且绑定正确的 check：这就是真实签发，直接采信并停止
- 平台不会自动创建同名 check、该名字只能由唯一可信 App 签发：无同名冒充可能，无需本方法
