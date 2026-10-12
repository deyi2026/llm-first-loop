---
method_id: anchor-verification-over-narrative-recovery-73fa76a07438
name: anchor-verification-over-narrative-recovery
description: 核对'过去的建议/交付是否落实'时，不要循环恢复旧报告全文：首次截断或检索无命中后，把旧报告当作待验证的声明清单而非证据。从预览与 git 历史提取每条建议的可查锚点（fix commit、record/EVO id、部署 gen/head、job id），逐个到权威源验证（git show / branch --contains、records 检索、status 回执）。验证通过→已落实；验证失败（如修复 commit 不在部署线上）→该失败本身即下一步行动项。若一致性检查（declaration_check）已标记旧报告含与回执不符的声明，则恢复原文更无证据价值。仅当某条建议不存在任何机器可查锚点时，才升级为更宽的原文恢复或向用户确认。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:886:eddb3f173d277042a11f
evidence_refs: learning:learn:633ff851b551
created_at: 2026-09-18T19:04:46.831421+00:00
updated_at: 2026-09-18T19:04:46.831421+00:00
---
## Trigger
用户要求确认'此前交付/建议是否已落实'，而过去的自述报告仅以截断形式存在（事件流折叠、日志截断）或 evidence 检索无命中，但预览或仓库历史中已可见报告所指涉的锚点（commit hash、记录键、部署代次、任务 id）

## Discriminator
一次恢复尝试已返回截断或无命中，且更早已可见两个事实：(1) declaration/consistency check 已标记该旧报告含与工具回执不符的完成声明——原文不具证据效力；(2) 预览与 git 历史已暴露每条建议的锚点（修复 commit 的权威 commit message、EVO id、gen/head、服务状态回执），每个锚点都可在权威源直接查询。二者合起来表明：验证锚点比恢复散文更便宜且更权威

## Short path
- 读当前权威回执（部署状态、服务 code_current、pending 队列），确立'现在'的真值基线
- 对旧报告至多做一次恢复尝试；无论成败，从预览与相关 git 历史提取每条建议的锚点：fix commit、EVO/record id、部署 gen/head、job id
- 逐锚点查权威源：git show 取修复的权威描述；git branch --contains 判断是否进入部署线；search_records 判断登记是否闭合；status 回执判断服务新旧
- 分类输出：源验证通过→已落实；验证失败（如修复不在部署线）→直接定义为下一步行动项，进入执行
- 仅当某条建议没有任何机器可查锚点（纯方向性建议）时，才升级为更宽的原文恢复或向用户澄清

## Stop conditions
- 每条建议都已映射到一个权威源的验证结果（git 输出 / 记录查询 / status 回执），状态表完全不依赖恢复出的报告原文
- 所有验证失败的条目均已转为明确的下一步行动并开始执行

## Verification
- 最终逐项'已落实/未落实'结论均引用 live 权威回执（branch --contains 输出、records 查询结果、服务 status），而非恢复的叙事文本
- 对每条'已落实'声明，核验所用权威源与该建议指涉的对象是同一锚点（同一 commit、同一记录键、同一服务）

## Counterexamples
- 用户要的就是上一轮报告的原文内容（原文本身即交付物）→ 恢复原文就是任务，本方法不适用
- 建议条目无任何机器可查锚点（如'以后考虑引入 A/B 评估'）→ 锚点验证无法分类，必须依靠原文或用户澄清
- 预览与历史中完全提取不出锚点（报告只以不可检索的摘要存在）→ 此时扩大恢复范围（提高 event limit、evidence 检索）才是正确的升级路径，而非强行套用锚点验证
