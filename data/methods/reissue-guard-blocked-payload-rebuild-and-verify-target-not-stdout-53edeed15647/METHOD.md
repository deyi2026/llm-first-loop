---
method_id: reissue-guard-blocked-payload-rebuild-and-verify-target-not-stdout-53edeed15647
name: reissue-guard-blocked-payload-rebuild-and-verify-target-not-stdout
description: 带安全护栏的 shell 里，脚本化文件变更被硬阻断且回执内嵌『可复制的等价姿势』（先落盘再受限解释器执行）时：阻断即零副作用（heredoc 内包含的写盘同样未发生），重试必须按建议姿势完整重建全部载荷、不假设先前中转脚本已存在或最新；重试 stdout 的 updated 不可信——旧文件执行会打印假成功；以目标工件内容级 grep 到新值为准，不符先核对中转脚本内容再修。本例 receipt 数值首次重试假成功，靠 grep 抓出旧文件后才真更新。
aliases: 被安全护栏拦了怎么重跑, heredoc 塞给 python 被硬拦, 脚本说改好了文件没变, 跑了旧脚本还报成功, 先写临时文件再 python 执行, 改完 grep 一下确认真改了
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:1706:272af95aa428b584121c
evidence_refs: learning:learn:e5f060b41796
created_at: 2026-11-14T00:49:31.852170+08:00
updated_at: 2026-11-14T00:49:31.852170+08:00
---
## Trigger
带安全护栏的 shell 环境中，脚本化变更以 heredoc 直灌解释器等姿势被硬阻断（如 E6_CATASTROPHIC_HARD / RULE-AI-36），阻断回执附带等价重发姿势（先落盘再 python3 -I 执行），需完成同一变更时；以及任何经中转脚本重试写操作后判断是否真正生效时。

## Discriminator
硬阻断回执本身证明该命令零副作用——heredoc 里包含的写盘也没发生；因此任何『重跑已有脚本』式重试都可能执行遗留旧文件，其 stdout（receipt updated）只证明跑了某个脚本，不证明目标工件内容已变。判别事实当时已在手：阻断回执 + 护栏给出的等价姿势。

## Short path
- 读阻断回执：确认零副作用，逐字摘出等价姿势（落盘中转路径 + 执行方式如 python3 -I）
- 按该姿势完整重建全部预期变更写入新脚本文件，不假设任何先前中转文件存在或最新；此后同类变更默认先落盘再执行，规避再次阻断
- 执行后立即对每个目标工件做内容级验证：grep/read 期望新值，不采信脚本 stdout
- stdout 报成功但工件未变 → 先读中转脚本文件内容核对是否旧文件/旧载荷，修正后重跑再验证
- 全部目标工件直接读到新值即停，进入 stage/报告等后续流程

## Stop conditions
- 每个目标工件都已直接读到期望新值（本例 receipt 与 freeze doc 均为 36/639），而非脚本声明
- 护栏明示等价姿势第二步仍会被拦（载荷含 push/全量测试/敏感路径/进程派生）→ 停止重发，改走 review_admission/提权审批

## Verification
- grep 目标文件出现期望新值且旧值不再占据权威位置
- 核对中转脚本文件内容与本次载荷一致（cat/sha），排除旧文件假成功

## Counterexamples
- 被阻断的是只读命令或回执未给等价姿势 → 不是落盘重发场景，按阻断类别走审批或换通道
- 载荷含受保护动作且护栏明示第二步仍拦 → 等价姿势无效，必须人工审批，不得借姿势绕行
- 软拒绝（accepted:false + 命名缺失字段）→ 用回执差分补字段重发即可，不涉及中转脚本与旧文件风险
- 声明式幂等工具调用以回执为真值 → 信任回执即可，无需对目标做内容级重读
