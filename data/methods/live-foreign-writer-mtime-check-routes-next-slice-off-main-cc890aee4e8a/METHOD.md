---
method_id: live-foreign-writer-mtime-check-routes-next-slice-off-main-cc890aee4e8a
name: live-foreign-writer-mtime-check-routes-next-slice-off-main
description: 在多会话共享仓库里回答『下一步做什么/在哪做』时，执行位置（main 还是独立 worktree）本身是必须当场核实的未知量：一次只读检查——porcelain 全清单 + 脏文件 mtime 对比当前观测时刻 + 协调回执里他 session 活跃度——若证明 main 上存在秒/分钟级新鲜的外来在途改动，就把新切片改路到独立 worktree（命名分支 + 以当前 main HEAD 为 base），用双方文件面是否相交预测合并冲突，并提醒冻结产物的门禁（full_test/push 审查）不能在移动中的树上跑。脏但陈旧或文件面重叠时按各自分支处理，不套此判定。
aliases: 别的会话还在写main我去哪干活, 树上有人正在写怎么办, main不干净新活开哪, 判断是不是有人在改仓库, 给下一步建议前先看树活不活, 并发会话抢同一个仓库
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:3304:3250055cbecd476bb623
evidence_refs: learning:learn:a7ed8622ecd7
created_at: 2026-11-08T22:27:26.457121+08:00
updated_at: 2026-11-08T22:27:26.457121+08:00
---
## Trigger
共享/多会话仓库中，用户要下一步建议，或要为新功能切片选择执行位置；协调回执显示存在其他 active session/演进管线，本切片预计要改代码并跑门禁

## Discriminator
脏树不是静态脏：未提交文件的 mtime 距当前观测时刻仅秒级~分钟级（本集 22:19:45 vs observed 22:19:46），且改动文件面归属另一项在途工作（subagent/* ≠ 本切片 peer/*）——活跃写者在场，对 main 的占用是持续的

## Short path
- 从协调/任务回执确认他 session 活跃度，以及本切片将触碰的文件面
- 一次只读命令拿三件事：porcelain 全清单、脏文件 mtime、当前 HEAD
- mtime 新鲜 => 判定活跃写者：建议在独立 worktree（命名分支，base=当前 main HEAD）开切片，不动 main
- 比对脏文件面与本切片文件面：不相交 => 预测合并冲突为空，但合并前按当时 main 复核一次；相交 => 先协调归属再谈排期
- 明确警示：冻结产物的门禁（full_test / push 审查）必须等树静止，移动的树会让回执失真
- 把仍需用户裁决的范围问题（如验收在本机还是远端节点）收敛成单独一个提问，不混进执行步骤

## Stop conditions
- 已给出带核实依据（status+mtime+HEAD）的执行位置与理由，且待决项收敛为一个明确问题
- 脏改动 mtime 陈旧（小时/天级）且无活跃他 session——转入陈留在途工作的澄清/收编流程，本判定不再适用

## Verification
- 新 worktree 的 base 与决策时的 main HEAD 一致（rev-parse 复核）
- 合并前重跑一次 status/HEAD：冲突预测（文件面相交性）仍成立
- 门禁/审查回执的产生时刻，树上无分钟级新 mtime 的写入

## Counterexamples
- 树脏但 mtime 已是几小时/几天前、协调回执也无活跃他 session：是陈留改动，应走澄清或保护性收编；worktree 只解决『新活在哪做』，不解决『旧账谁清』
- 外来在途改动与本切片文件面直接重叠：worktree 隔离不了语义冲突，必须先与归属方协调或等其落地
- 单人单会话仓库且树干净：直接在当前分支做，开 worktree 是纯开销
- 外来写者按提交粒度原子落盘、树随即转净：mtime 新鲜只说明『刚写过』，不说明『长时段占树』，可按提交边界穿插而不必隔离
