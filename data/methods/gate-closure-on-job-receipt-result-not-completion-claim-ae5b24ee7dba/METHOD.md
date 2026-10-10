---
method_id: gate-closure-on-job-receipt-result-not-completion-claim-ae5b24ee7dba
name: gate-closure-on-job-receipt-result-not-completion-claim
description: 当用户口头『完成了』或定时唤醒点名某后台 job 并要求执行收口动作（commit/task done/checkpoint/对外宣布）时，完成状态与 exit=0 都不是收口授权：收口门槛是约定中写明的『结果』本身。应直接取 job 回执并解析输出中的 FAILED 行与『N failed, M passed』汇总；尤其当命令含管道（如 | tail -3）时，回执 exit code 只反映管道末端命令，会把测试失败掩蔽成 0。结果非绿则挂起收口链，按失败断言自含的修复契约（登记文件、节名、review 先例格式）做最小修复并机械排查同类违例，目标用例回绿后才恢复原定收口顺序。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:64924088-0141-4a3a-87ee-81f09678620d:275:815f10385a6971dc5e4b
evidence_refs: learning:learn:a87c1b33972d
created_at: 2026-10-10T10:32:44.378210+08:00
updated_at: 2026-10-10T10:32:44.378210+08:00
---
## Trigger
存在口头完成声明（如『完成了』）或定时唤醒消息点名某后台 job 已完成，且下一步将执行依赖该 job 结果的收口动作（提交、task done、checkpoint、对外宣布完成）

## Discriminator
两条当时已知事实：① 唤醒消息原文已写明『检查后台全量 pytest（job-…）是否完成；完成后按结果决定收口』——收口门槛被明确定义为结果而非完成状态；② 回执命令行含管道（pytest … | tail -3），故 status=done/exit=0 只反映管道末端命令，测试失败被掩蔽；结果真值只存在于回执输出尾部的逐条 FAILED 行与 failed/passed 计数

## Short path
- 从完成声明/唤醒消息中提取被点名的 job id 与决策规则，把唯一未知量定为：结果是否达到收口门槛
- 直接取该 job 回执（status+输出尾部），解析 FAILED 行与 failed/passed 计数；命令含管道时不把 exit code 当成功证据
- 若结果非绿：挂起收口链，读失败断言全文——ratchet/guard 类断言通常自含修复契约（指名登记文件+节名+流程），据此定位而非先宽搜文档
- 按断言指名的登记/审计格式（含 baseline 中同类先例的 review_rationale+reviewed_new_signatures 结构）做最小修复，并机械排查新代码内同类违例（如 grep 确认仅一处 env 读）
- 单独重跑目标失败用例至全绿，再恢复原定收口顺序（提交→task done→checkpoint）

## Stop conditions
- 回执输出显示 0 failed / 汇总全绿（或 job 语义成功），收口门槛已满足
- 失败被归因为与本次改动无关的既有问题且约定不阻塞：另行处理，不在本次收口内修复
- 回执缺失或输出被截断到不含结果汇总：结论挂起，改取完整日志或重跑，不凭 exit=0 收口

## Verification
- 目标失败用例单独重跑为绿，并记录计数变化（如 2 failed→0 failed）作为收口依据
- 收口陈述引用回执中的具体计数/FAILED 行，而非『完成了』或『exit=0』

## Counterexamples
- 后台命令无管道、exit code 语义可信（非零即失败）：直接以 exit code 判定即可，不必解析输出内容
- job 完成但收口动作并不以其结果为门槛（结果仅是参考指标）：完成状态即可触发收口，本方法不适用
- 要核实的是共享可变资源在有并发写者时的『当前终局状态』：那属于重读权威记录+时间戳快照一类（fresh-read 方法域），不是本方法的 job 回执结果门槛
- 无任何权威回执可取且无法定位 job id 的口头声明：需其他验证途径，本方法无法机械执行
