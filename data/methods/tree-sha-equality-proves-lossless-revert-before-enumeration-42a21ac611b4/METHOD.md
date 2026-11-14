---
method_id: tree-sha-equality-proves-lossless-revert-before-enumeration-42a21ac611b4
name: tree-sha-equality-proves-lossless-revert-before-enumeration
description: 历史含并发写入事故（误加提交B随后被revert）且需核验『重复项确实消失、净效果仅剩预期增量A、无夹带』时，先用一次rev-parse批量取事故链各提交tree SHA：若tree(revert提交)==tree(事故前正确提交)，即得数学级恒等证明——B不在HEAD树、零残留——从而跳过读被回退内容与枚举周边目录全量清单；残余存在性/计数问题用模式定点检查（cat-file -e、ls-tree|grep）一次打包。历史范围问题（预推送扫描）单独按range处理：被revert的blob仍在中间提交，必须扫全区间。tree不等则立即降级为逐提交diff审查，不得声称无损。
aliases: revert之后怎么证明没误删别的, 误并发提交回滚无损核验, git 树哈希相等 证明回退干净, 重复文件回退后只剩一份怎么审, audit lossless revert via tree sha, 回滚是否精确恢复到事故前状态
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d324e1a9-2f27-4e42-aaf3-680d2917311c:103:96b797e4affa8baf9786
evidence_refs: learning:learn:be175673c166
created_at: 2026-11-14T10:44:07.731616+08:00
updated_at: 2026-11-14T10:44:07.731616+08:00
---
## Trigger
历史含并发写入事故（误加提交随后被revert），任务要求核验revert无损性断言：『重复项确实被回退、净效果仅剩预期增量、无误删/夹带』；或审计者正准备枚举被回退内容、全量列目录来回答该问题。

## Discriminator
一次rev-parse/log批量输出中，tree(revert提交)与tree(事故前正确提交)的tree SHA逐字相等（本集035f78d6==035f78d6，在首个git批次已可见）；辅以净diff name-status恰为预期增量、排除该路径外diff为0字节。相等即恒等证明，把『B还在吗/有没有误删/有没有夹带』整类枚举问题一次闭合，无需逐页恢复截断的全目录清单。

## Short path
- 一条git批量只读命令取事故链各提交commit/tree/parent、status porcelain、log、净diff name-status、排除预期路径外的diff字节数
- tree(revert)==tree(事故前提交)⇒直接下无损结论：被回退对象不在HEAD树、零残留；不读被回退内容、不枚举周边目录
- 残余未知量（是否仅剩一份）用模式定点检查一次打包：cat-file -e HEAD:<B路径>应失败、ls-tree|grep <命名前缀>计数恰为1
- 只对预期增量内容做语义审（读其全文、与changed-paths集合比对、引用证据文件存在性）
- 历史范围问题（预推送扫描）单独按range语义处理：被revert的blob仍在中间提交，扫全区间，不受HEAD恒等影响
- 裁决绑定精确HEAD/tree SHA后停止，不再做枚举或分页恢复

## Stop conditions
- tree SHA相等+定点检查通过+增量内容语义审完毕⇒输出裁决，停止任何进一步枚举/分页恢复
- tree不相等（revert夹带修复或手工解冲突）⇒立即降级为逐提交diff审查，不得声称无损
- 事故前提交不在当前历史（被rebase改写）⇒改用重建树或对parent链diff替代恒等比较

## Verification
- 独立复算 git diff --name-status <基>..HEAD 恰等于预期增量清单
- cat-file -e HEAD:<被回退路径> 确实报不存在
- 安全/门禁扫描range覆盖事故中间提交且PASS（坏blob仍在推送历史）
- 最终HEAD/tree SHA与任务声明逐字一致，worktree porcelain为空

## Counterexamples
- revert提交同时携带其它修复或冲突手工解决⇒tree必不相等，恒等证明失效，必须逐提交审
- 要回答的是历史/推送内容而非终态（安全扫描、合规审计）⇒HEAD树恒等无信息量，中间提交仍须逐个扫
- 误并发改的是既有文件而非新增文件⇒恒等anchor须选含正确版本的提交，净diff须逐条核对而非只数文件数
- 待核验的是工作区未提交状态⇒提交树恒等不覆盖，须另查status/diff
