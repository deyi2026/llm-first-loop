---
method_id: receipt-named-next-call-first-9eb1b18e44d1
name: receipt-named-next-call-first
description: 异步工具回执（后台 job 启动、publish/convergence 块、准入回执）常显式点名下一步查询入口或精确调用参数，如『用 job_output(job_id=…) 查询退出码与输出』、next: service_control(action=restart, target=…, expected_generation=…)。本集两次未沿此边走：wait 回执已给出 state=completed/exit=0 后，仍先探测 Evidence 层（一次不可用+一次空搜索）才调用被点名的 job_output；restart 首调漏掉被点名的 target 字段导致参数契约失败。方法：出现新未知量时，先扫描回执中被点名的入口/参数并逐字执行；仅当该入口失败、无关或已试过，才换检索层或自行组参。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:1960:4c5544a9fb58c9bb7aa2
evidence_refs: learning:learn:1322b5619546
created_at: 2026-10-18T12:12:00.300454+08:00
updated_at: 2026-10-18T12:12:00.300454+08:00
---
## Trigger
异步/后台工具回执文本中显式点名下一步查询入口或精确调用形状（tool 名+必填字段），且当前存在一个该入口可直接回答的未知量（如后台任务终态与输出尾部、待重启服务清单）

## Discriminator
回执中存在字面可执行的 next 指令（『用 X(job_id=…) 查询…』或 next: 'service_control(action=…, target=…, expected_generation=…)'）；同时上一跳回执已解掉部分未知量（wake_reason=job_terminal, exit=0），剩余未知量恰是被点名入口所回答的内容。判别要点：点名入口须与当前未知量语义对应，而非回执中的规则告示或样板行。

## Short path
- 每收到异步回执，先提取其中字面点名的下一步入口与完整参数（tool 名、job_id、target、expected_generation 等）作为待用边
- 下一未知量出现时（如『要看全量门禁尾部汇总』），直接按点名入口逐字调用，不先探 Evidence/搜索等其他检索层
- 点名入口一次返回即取得权威事实（exit=0+输出尾部），停止再确认，转入收尾动作（清理/发布）
- 对 next: 字段给出的动作照抄全部字段；仅当点名入口调用失败或语义无关时，才回退到其他检索层或自行补参

## Stop conditions
- 被点名入口已成功回答当前未知量（同一来源同时给出终态与输出尾部/受理回执）
- 回执中除点名 next 外的其余文本经判断为规则告示或样板说明，不作为动作指令执行

## Verification
- 核对取得事实的来源与回执点名入口一致：job_output 的 job_id 与启动回执一致；restart 调用参数覆盖 next 字段列出的全部字段（target、expected_generation）
- 确认没有先于点名入口对其他检索层的无效探测（无 Evidence 不可用/空搜索类失败，无参数契约返工）

## Counterexamples
- 回执同时含规则告示/审校提示行（如 review_gate『仅工具文本，未核验』），这不是可执行 next，机械逐行执行会引发错误动作——需语义筛选哪一行是动作指令
- 任务目标本身就是读取某持久 Evidence 工件（用户点名要求）时，Evidence 检索是目标而非绕路，不适用
- 点名入口已尝试且失败（如当前会话无权访问该 Evidence/入口），此时回退其他检索层是正确分支
