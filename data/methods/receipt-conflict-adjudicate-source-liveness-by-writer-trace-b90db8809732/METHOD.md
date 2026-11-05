---
method_id: receipt-conflict-adjudicate-source-liveness-by-writer-trace-b90db8809732
name: receipt-conflict-adjudicate-source-liveness-by-writer-trace
description: 聚合面板/派生视图与控制面权威回执对同一状态事实（部署sha/版本/健康）给出矛盾值、且派生端响应自述其数据源时，第一未知量不是『哪个值对』而是『派生端读的那个源还有没有活写入者』：先 grep 真实子系统是否仍写该源（无命中=死的历史记录，mismatch是假信号），再从写入者源码的持久化路径常量直接定位活账本，验权威标记+完整身份后把派生端改接活账本，回退时如实标注source/degraded并为每个回退分支补测试。
aliases: 面板显示的版本和服务实际跑的对不上, 两个回执矛盾信哪个, dashboard数据源过期排查, board读到旧部署记录, 聚合视图接了死数据源, 假mismatch怎么定位
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:d0e6ba0c-dfdb-4a7e-b110-850f0ae238a6:974:9c12f3f31212a00dcdd6
evidence_refs: learning:learn:a7b7e5478ecc
created_at: 2026-11-05T12:53:06.318483+08:00
updated_at: 2026-11-05T12:53:06.318483+08:00
---
## Trigger
聚合器/面板/派生视图输出的状态字段与控制面权威回执矛盾，且派生响应自述数据来源（如source字段指向某目录）；控制面回执已带内嵌verify=ok的身份核验（pid/head/generation）。

## Discriminator
两个各自看起来权威的值冲突 + 派生端自述source指向静态/审计目录 + 控制面回执verify=ok且给出具体身份（pid/head/generation）——该组合在冲突暴露当时就已存在，把假设空间从『部署真漂移/回滚/需重验部署』缩到『派生端接在已停写的死源上』，下一步只需一次grep验证写入关系。

## Short path
- 并排两回执：确认冲突仅集中在派生端引用的那一个字段，控制面身份已内嵌verify=ok，不再重验部署本身
- 对派生端自述的source路径，grep真实子系统的写入点：无命中即死源（历史人工记录），mismatch是假信号
- 在写入者源码中检索持久化路径常量（如 _RESTART_RECEIPT_REL）得到活账本路径，不要全目录枚举data/去猜
- 读活账本：校验权威标记（authoritative=true）与完整身份（git_head_full）和控制面回执一致
- 改派生端优先读活账本；账本缺失/非权威/无完整身份时回退旧源并如实写source与degraded；每个回退分支各补一条测试

## Stop conditions
- 活账本已验证（权威标记+完整身份）且与控制面回执一致，派生端输出source已指向活账本
- 若grep证明子系统仍在写旧源，则mismatch是真信号：转向查部署是否真失败/回滚，停止修改读取端

## Verification
- 非权威回执或账本缺失时，派生端输出回退source与degraded，而不是假mismatch
- 修改后派生端的部署值与控制面status回执逐字段一致（sha/generation/时间戳新鲜度）
- 每个回退分支（缺失/非权威/无sha）均有测试覆盖

## Counterexamples
- 矛盾源于部署真失败或已回滚：面板mismatch是正确告警，『修面板让它一致』会掩盖事故
- 旧目录是合规/合同指定的审计真相源（滞后也必须读）：应修写入方而非让读取端绕开审计源
- 只有单一回执、无第二来源矛盾时，不存在源裁决问题，直接使用该回执即可
- 活账本存在但无权威标记（如子代理手工跑脚本留下的回执）：不能当部署事实，必须走回退并显式降级
