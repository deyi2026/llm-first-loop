---
method_id: named-label-check-against-authoritative-registry-before-implementation-a6207ad19e5c
name: named-label-check-against-authoritative-registry-before-implementation
description: 指令引用一个具名阶段/规格/口径标签并假定其已立项，但未给路径、ID或定义引用时：先直接读权威登记处（设计文档阶段表/规则/契约）的规范枚举。若标签缺席且检索回执显式miss，即判定为前轮口头建议而非既有口径；对权威面（受跟踪的docs/src，排除venv/.releases/备份）做一次有界否定性grep即止，不再全库扫描或枚举records/outputs。然后把注释性说法映射到可观测的真实缺口（数据分布、代码注释、账本语义），先在登记处写入定义锚点、用实质标题立项，标签取舍交owner裁决；不按猜测口径写代码。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:638:1b6b4c62eb14a519380c
evidence_refs: learning:learn:4ee37fb19e1a
created_at: 2026-10-15T01:33:36.008459+08:00
updated_at: 2026-10-15T01:33:36.008459+08:00
---
## Trigger
用户指令引用具名阶段编号/规格/口径标签（如'接 P0c（某某口径）'）并默认其已被权威立项，但指令中未附路径、ID或可追溯的定义引用

## Discriminator
权威登记处（如设计文档的阶段实施表）已被定位并直接读取，其规范枚举中不含该标签，且首个检索回执为显式miss（非超时/截断）。两条同时成立即可把'可能定义在某处'收缩为'标签是未落盘的口头建议'，无需继续在venv/.releases/records等噪声面做宽枚举

## Short path
- 由标签名定位其应属的权威登记处（设计文档/规则/契约），直接读其规范枚举（如阶段实施表），解决未知量：该标签是否已被立项
- 枚举缺席+检索miss ⇒ 假设：标签是前轮对话的未落盘建议，而非既有验收口径
- 对受跟踪的权威面做一次有界grep（标签+释义关键词，显式排除venv/.releases/供应商目录），确认否定后立即停止验证
- 从既有可观测工件（状态分布统计、代码注释、账本计分语义）提取释义所指向的真实缺口，而非从标签字面猜测验收标准
- 先提议在登记处写入定义锚点、以实质内容重新立项，标签保留与否交owner确认；获裁决前不写实现代码

## Stop conditions
- 登记处枚举已读+一次有界权威grep完成后，否定性结论即确立；停止任何进一步的全库内容搜索、records检索或outputs枚举
- owner对标签与实质的裁决到手之前，不进入实现阶段

## Verification
- '无权威定义'的断言必须引用已读到的登记处具体章节与有界grep的实际范围，使结论可复算
- 后续实现的验收口径必须能回溯到实现之前写入登记处的定义，而非事后补写或自造'通过'

## Counterexamples
- 标签是用户为全新功能现场起的新名字，缺席是预期行为：直接进入定义与实现流程，无需否定性审计
- 标签合法定义在主登记处之外（任务跟踪记录、commit message、旧版本文档）：有界搜索会命中，此时以命中处为锚继续执行，而非拒绝
- 该领域根本不存在规范登记处：登记处检查不可行，直接向owner索要规格，不做负空间搜索
- 注释性说法无法映射到任何可观测缺口：只向owner澄清，不自行构造貌似合理的替代任务并实施
