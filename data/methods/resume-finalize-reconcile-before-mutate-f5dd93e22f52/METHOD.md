---
method_id: resume-finalize-reconcile-before-mutate-f5dd93e22f52
name: resume-finalize-reconcile-before-mutate
description: 会话经长等待/超时恢复，且已被告知命令被重复发起或存在被截断的并行执行段时，共享持久状态（git 历史、index、设计文档 Status）可能已被『过去的自己』推进。执行 commit/amend 等收尾变更前，先用一次只读对账（log --oneline、status、diff --cached --stat）核对『我以为还欠什么』；变更回执（files changed 数、相邻 log、residual 列表）必须与预期逐项对账，不一致即冻结后续变更，先取证（git show --stat + 统一 event stream）再修复：未 push 时 amend 改名而非叠加同名提交；文档引用的 commit hash 必须在 log 中验证存在后才可复述。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9ceab5d6-9c2f-4cf4-a73d-9ed7ecee9969:966:3e70f6248c63cdc215cf
evidence_refs: learning:learn:cb9400fc3f6a
created_at: 2026-10-02T02:57:43.378820+08:00
updated_at: 2026-10-02T02:57:43.378820+08:00
---
## Trigger
会话在长等待/超时后恢复，用户或环境已提示命令被重复发起、存在并行或截断执行段，且即将对共享仓库执行 commit、amend 等收尾变更动作。

## Discriminator
当时可见的对账事实：(1) 用户明确指出『时间到了之后又重复发起命令』——本会话存在重复执行风险；(2) 提交回执与预期矛盾：预期多文件 A2 提交，回执仅 '1 file changed, +2/-2'，且同一回执的 log 片段已出现两个同名提交和一个非本段发起的中间提交；(3) 回执的 residual 列表全部是未暂存（空格-M）修改，index 中不存在预期的 A2 文件。任一成立即说明共享状态已被并行段推进，不能再按『待办仍欠』的假设继续变更。

## Short path
- 恢复后、首次收尾变更（commit/amend）前：git log --oneline -5 + git status --short + git diff --cached --stat，与预期待办逐项对账
- 对账发现目标工作已被提交（同名/同内容 commit 已存在）→ 放弃重复提交，只补记录与汇报
- status 打印与 commit 分开执行，保留回执异常时分支的能力（禁止 print && commit 单链）
- 提交回执与预期不符（files changed 数异常、出现未知相邻提交）→ 冻结后续变更；git show --stat + 统一 event stream 取证并行段已做之事
- 修复：未 push 则 amend 改掉误名提交；逐条验证文档 Status 引用的 hash 是否存在于 log，不存在的改为『代码在树、commit 待落』

## Stop conditions
- 权威 log + event stream 已澄清并行段动作；amend 后无重复同名提交；下游记录与真实 hash 一致 → 停止，且不动非本委派范围的 working tree 修改
- 预检对账一致（diff --cached 与目标吻合、log 无未知提交）→ 正常提交一次即停止，不启动取证循环

## Verification
- 修复后 git log 中不再有重复 subject 的提交，汇报中的 hash 链与 log 实际输出一致
- 文档 Status 中每个被引用的 commit hash 都能在 git log / git cat-file 中找到，且状态措辞（COMMITTED vs in-tree pending）与事实一致
- amend 的安全性有显式依据：分支未 push，且并行段最后动作已静默足够久

## Counterexamples
- 干净单飞会话（无超时/重复执行信号）：正常 stage→commit；做一次廉价预检即可，不应触发『怀疑并行段』的调查分支
- 提交回执与预期一致、log 无异常：不做取证循环，直接进入下一步
- 分支已 push 或多人共享：amend 改写历史不安全，应改用新提交/revert 修复命名与记录问题
- 权威状态在远端 ref 而非本地 log（他人已 push）：应对账远端权威 ref，本方法的本地 log 对账不适用
