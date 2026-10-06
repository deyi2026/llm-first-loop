---
method_id: harvest-full-write-contract-on-first-gate-rejection-76b1a4f39cee
name: harvest-full-write-contract-on-first-gate-rejection
description: 校验型写入存储（experience/method/evidence 等 gated record store）多采用 fail-fast 校验：每轮只报一个未满足项，逐字段修补必然产生多轮 fix-reject 往返。首次被拒且回执为处方性文字时，把它当作不完整 spec 而非全部要求：合并回执要求与回执引用的持久规则记录，一次性补齐该 status 声明的全部捆绑要求（evidence、可执行当前性验证动作等），用 1 次契约读取 + 1 次完整重试替代 N 轮单字段修补。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:918cb167-56ff-4666-9f15-32f98b72c356:506:4d2065bee18e5c9b62a9
evidence_refs: learning:learn:1c08c3b65bb6
created_at: 2026-10-06T16:17:47.686176+08:00
updated_at: 2026-10-06T16:17:47.686176+08:00
---
## Trigger
向带校验门的持久化存储写入带状态声明的记录（如声明 verification_state=verified 的 save 调用），首次写入被参数/校验错误回执拒绝，且回执给出文字化缺失要求（如 'verified 必须提供 evidence'）而非纯错误码/超时。

## Discriminator
处方性、条件化的失败回执本身证明该门存在按 status 捆绑的要求契约（首次回执：verified⇒evidence），且这类验证门的要求通常不止一项；若回执引用持久规则 ID（本集第二次回执引 EVO-20260923-6fe23c9b），说明完整要求集有书面出处，可在重试前一次性读取，不必靠逐轮报错暴露。

## Short path
- 首次被拒：把回执原文记为 spec 第一条，但不当成唯一要求
- 先查契约再重试：按回执中的门名/引用规则 ID 检索规则库，枚举该 status 的全部捆绑要求（如 evidence + 可执行当前性验证动作：命令+期望结果）
- 一次性改写卡片满足全部要求后做单次完整重试
- 若仍被拒且指出新要求，重复一次 harvest→complete-retry
- 写入成功且状态与声明一致即停止

## Stop conditions
- 写入回执 success 且 verification_state/目标状态与声明一致
- 规则检索显示该 status 无其他捆绑要求且已列项全部满足
- 回执为非契约错误（timeout/权限/磁盘），转环境修复路径，本方法不适用

## Verification
- 成功回执确认目标状态生效（本集：save_experience status=active verification_state=verified）
- 卡内验证要求为可执行动作（命令+期望结果），而非纯断言式描述
- 完整重试次数≤1，显著少于逐字段修补所需的轮数

## Counterexamples
- 回执是 transient/系统错误（timeout、权限、连接失败）而非契约校验错误：无可 harvest 的要求，直接重试或修环境
- 校验器一次性列出全部未满足项：照单补齐即可，再去读规则属浪费
- 写入无状态声明、无校验门（普通文件输出、临时便签）：不存在捆绑要求集
- 门明显无文档化规则且回执只列一项：单字段修复就是最短路径，不应为找契约扩大搜索
