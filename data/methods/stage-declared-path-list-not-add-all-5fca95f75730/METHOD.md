---
method_id: stage-declared-path-list-not-add-all-5fca95f75730
name: stage-declared-path-list-not-add-all
description: 合并/清理前需把未提交改动分组落定时，若此前 diff/status 已枚举出精确待提交清单（或已声明子集计划），且仓库含未跟踪生成产物与 pre-commit 内容扫描 hook，则 staging 必须按显式路径清单执行，并在提交前断言 cached 集合恰等于计划；被 hook 拦截后只撤销被点名路径。本集改用 add -A 卷入约 13 万行 evals 运行产物，触发 60s 超时、多轮撤销与重复扫描，最终仍回到精确清单提交——所需清单在动作前早已在手。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:1651:136271c4da6184b8acc0
evidence_refs: learning:learn:c13f0cf9a84e
created_at: 2026-09-18T06:52:09.001862+00:00
updated_at: 2026-09-18T06:52:09.001862+00:00
---
## Trigger
需要提交一组已知文件（如合并前快照、分组落定），同时满足：(a) 先前命令已输出精确文件清单或计划文本已声明子集；(b) 仓库存在未跟踪生成产物目录或会逐文件扫描的 pre-commit hook

## Discriminator
此前 git diff --name-only 已给出确切的 15 个文件清单（含 mtime 与 diff 规模），且扫描器报错点名了具体违规文件并给出修复路径——待提交集合在动作前已是已知事实，用宽通配符重新推导 staging 只会引入未知变量（未跟踪产物 sweep + hook 全量扫描成本）

## Short path
- hook 拦截后，只按报错点名的路径/目录撤销 staged 状态，保留其余已分组内容，不改用全树命令
- 按已知显式路径清单 stage 目标文件（逐路径 add，禁用 add -A / add .）
- 提交前断言：git diff --cached --name-only 逐项等于计划清单，且 --stat 总规模与已知 diff 量级一致
- 断言通过即 commit；若不符，仅修正 staging 差集后重试一次，不再做全树操作
- 进入合并/后续主流程

## Stop conditions
- cached 清单与计划逐项一致且 commit 顺利通过扫描 hook
- 一次差集修正后仍不匹配则停止，转为人工审查 staging，而非再次全量 stage

## Verification
- 每次 commit 前比对 git diff --cached --name-only 与计划清单（数量+路径逐一对应）
- 检查 git diff --cached --stat 的总行数量级是否与已知 diff 规模吻合（出现数量级跃升即 sweep 事故信号）
- commit 后用 git log/status 确认仅产生预期提交、工作区未被动污染

## Counterexamples
- 计划本身就是提交整个工作树（初始导入、有意的全量快照），且已确认无生成产物混入——此时宽 staging 是正确手段
- 未跟踪的运行产物正是本次交付物（如结果归档任务），显式排除它们反而漏交
- 待提交集合未知且任务目标就是发现要提交什么——此时缺的是发现流程，staging 纪律不适用
