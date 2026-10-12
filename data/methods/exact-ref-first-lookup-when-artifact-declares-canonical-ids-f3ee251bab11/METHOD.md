---
method_id: exact-ref-first-lookup-when-artifact-declares-canonical-ids-f3ee251bab11
name: exact-ref-first-lookup-when-artifact-declares-canonical-ids
description: 工件（方法卡/记录/提交）的元数据已逐字声明唯一 ref（evidence_refs、source_episode_refs、method_id、commit SHA）时，溯源与登记一律先用 ref 原文作为查询键或必填参数：对记录库做一次精确检索即可命中来源；登记类调用直接携带 canonical ID。把 ID 混入自然语言关键词组合会 miss 并触发换措辞重试；漏带 ID 字段则报参数错误。仅当精确 ref 未命中或工件确实无 ref 时，才有界地退回关键词检索。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:1389:885cc8b5500065e21210
evidence_refs: learning:learn:de3a96cec41b
created_at: 2026-09-20T04:03:05.018409+00:00
updated_at: 2026-09-20T04:03:05.018409+00:00
---
## Trigger
需要验证/溯源一条自带 canonical refs 的记录（如核实方法卡的来源 episode、做 qualification 登记），或调用以该记录 ID 为必填参数的登记类工具时

## Discriminator
工件 frontmatter/元数据中已逐字存在唯一标识（如 evidence_refs: learning:learn:<hash>、method_id、source_episode_refs、commit SHA）——待定位对象已被精确命名，构造模糊关键词查询只会扩大搜索空间

## Short path
- 读目标工件，提取其声明的 canonical refs（未知量：来源是否真实存在且支持裁决）
- 用 ref 原文对记录库做一次精确检索，不做 ID+概念词混合查询（未知量：来源记录内容与结局）
- 命中后核对其结论/结局是否满足裁决要求，即可下判断
- 登记/资格化调用逐字携带 method_id / episode ref 作为必填参数，不再改写
- 若精确 ref 未命中：仅一次有界关键词退回；仍 miss 则报告证据不足，停止换措辞枚举

## Stop conditions
- 来源记录已命中且其内容足以支持裁决（如来源 episode 以成功收尾），即停止溯源
- 精确 ref miss 且一次关键词退回仍 miss：停止扩散，输出证据不足结论而非继续检索

## Verification
- 命中记录的 ref 与工件声明 ref 逐字一致
- 登记回执中 method_ref / qualification 引用与工件 method_id 完全一致
- 过程中无因关键词混合导致的重复检索，无缺 ID 参数的失败调用

## Counterexamples
- 开放性语义发现（如『找相似方法候选』），无具体 ref 可用：概念/关键词检索才是正确手段，本方法不适用
- 存储已改键/重命名导致精确 ref 合法 miss：应改用别名/旧键检索，而非机械重试同一 ref 或直接断言来源不存在
- 工件声明多个互相冲突的 ref：需先仲裁哪个 ref 权威，不能默认取第一个去查
