---
method_id: admission-scope-from-execution-surface-not-change-set-e3d253535a5b
name: admission-scope-from-execution-surface-not-change-set
description: 向带 scope(patch/tree/paths)选择的审查/准入门为特权动作（git push、全量测试）请求准入时，范围合法性由动作的执行面推导，不由本次改动面决定：git push 搬运的是 refspec 源 commit 的整树对象，即便只改了 6 个文件，patch scope 也不适用，授权面会小于执行面。只有执行面本身按工件绑定的动作（如稿件发布）才用工件级范围。schema 未写明 kind×scope 合法组合时，从『这个动作真正搬运/修改什么』推默认范围；若仍被命名错误码拒绝，按差分机械重发一次即可，不做宽调查。本集首发起 patch+6 文件被 review_scope_not_applicable_for_git_push 拒后重发整树通过。
aliases: git_push 审查能不能只审改动的文件, review_admission scope 选 patch 还是 tree, push 前审查按整树还是按改动文件, 审查范围和动作执行面不一致被拒, 授权面小于执行面怎么办
status: candidate
source_model: deepseek/deepseek-flash
source_episode_refs: episode:4aea0dd4-3b3b-4874-8090-870678230df3:1334:2d8ef39d072ec0cd528e
evidence_refs: learning:learn:35991d67f587
created_at: 2026-11-03T16:41:49.775954+08:00
updated_at: 2026-11-03T16:41:49.775954+08:00
---
## Trigger
带 scope 参数的准入/审查闸前，为 kind=git_push（或其它整树执行面动作）发起审查请求，且工具 schema 未声明各 kind 的合法 scope 组合；或下意识想按『本次改动文件清单』缩小审查范围

## Discriminator
该 kind 的执行基底是什么：push 搬运 commit 对象=整树；若拟请求范围（paths 冻结面）小于执行面，则该范围对该 kind 不适用，即便受理也授权不足。改动文件数（如 6 个）不是范围依据，这一推断在发起前即可从 schema+动作语义得出，无需先撞一次拒绝

## Short path
- 读准入工具现行 schema，确认 scope/kind 合同；未声明组合约束则进入推导
- 对目标 kind 只问一个未知量：该动作真正搬运/修改的底物是整树 commit 还是具体工件
- 执行面=整树 → 请求 tree（或不带 scope/paths），不因改动少而声明 patch+paths；执行面=工件级 → 才声明 patch+paths
- 受理后核对回执 scope.effective 与 consumable_scope.authorizes 是否覆盖执行面
- 若仍被命名 reason 拒绝（如 xxx_not_applicable_for_kind），把 reason 翻译成参数差分机械重发一次，不展开调查

## Stop conditions
- 回执 accepted 且 consumable_scope.authorizes 覆盖特权动作完整执行面
- 或命名拒绝码已翻译为参数差分并一次重发成功
- 资格签发后停在用户对外授权边界（审查 PASS ≠ push/publish 授权）

## Verification
- 对 push 类：回执 scope.effective==tree，push_src_commit==当前 HEAD
- PASS 资格的 consumable_scope.not_covered 为空或明确不含将执行的面
- 执行特权动作前 HEAD 未移动、tracked 面与受审面一致

## Counterexamples
- article_publish 类动作执行面就是稿件+随稿工件：manuscript_path/artifact_paths 级绑定才是正确范围，不需要整树
- schema 或门文档已明确写出 kind×scope 矩阵时，直接照文档选择，无需从底物推断
- 拒绝码自描述且重试零成本、门槛低时，按默认发起再按差分重发亦可接受，不值得事前长推导
- 非授权闸的本地私跑测试（只想验证局部改动）不适用：按改动面缩范围在那里是正确的
