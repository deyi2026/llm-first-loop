---
method_id: parallel-executor-completed-verify-then-owner-register-91454a8b4b00
name: parallel-executor-completed-verify-then-owner-register
description: 多会话共享工作区里，外部审批/状态翻转回执要求『核实后继续执行』某工作项时，若登记簿显示已有外来执行者活动、或本会话协调收件箱已有他方完成通报，『继续执行』的真实剩余动作往往只是归属方登记：切换为核验模式——pwd 锚定仓库、merge-base 验证声称 commit 已在远端祖先链、直读实现 diff、本地复跑具名测试（护栏类变更不采信自报）——再以归属会话登记完成；并用同一实况重审 Goal 残留的 doing/blocked 项（阻塞前提可能已被并行活动消除），收口时使用系统铸造的 evidence:// 凭证而非手工拼引用。
aliases: 别人已经做完了还要自己重做吗, 跨会话代实现后归属登记, 审批后先查并行会话是不是已实现, 不采信自报先复跑测试再登记完成, 推送阻塞可能已被其他会话解除
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:3319adeb-e84e-4f85-ae10-8306e3d98fb1:758:55b9cfc350e42ed139a7
evidence_refs: learning:learn:b8678156713c
created_at: 2026-11-06T16:03:10.871663+08:00
updated_at: 2026-11-06T16:03:10.871663+08:00
---
## Trigger
外部审批/状态翻转回执要求本会话『核实状态后继续执行』一个带 ID 的工作项（演进单/变更单），且处于多会话共享工作区（存在他方会话 action_trace、help 收件箱等协调面）

## Discriminator
按 ID 直查登记簿的 exec 记录显示该工作项已处于活动执行态且执行者不是本会话（本会话自翻转后零动作），或会话绑定的 help 收件箱已有点名该工作项的他方待处理通报——此时第一未知量是『执行者做了什么、欠我哪一步归属动作』，而不是『我怎么实现』

## Short path
- 回执核实：用回执给出的 ID 定点查登记簿记录（状态/执行者），一次查询闭合『翻转是否属实』
- 若记录显示活动执行者非本会话：先查会话绑定协调通道（help 收件箱）按工作项 ID 过滤读通报全文——『继续执行』常已退化为『归属方登记』
- 切换为归属方核验模式：pwd 锚定真实仓库路径；merge-base --is-ancestor 验证声称 commit ∈ 远端；直读实现 diff/源码；本地复跑具名测试文件（含应拦保持用例，不采信他方自报）
- 以归属会话登记完成，note 记录实现方身份 + 独立核验事实链（commit 祖先/测试结果/实战使用先例）
- 用同一实况重审 Goal 残留：doing/blocked 项的阻塞前提可能已被并行活动消除（如 push 阻塞 vs 远端已含该 commit），以祖先关系判定而非重执行；任务收口引用系统铸造的 evidence:// 凭证

## Stop conditions
- 登记落盘（registered=True）且 Goal 残留项逐项按实况裁决完毕，无剩余未知量
- 执行方声称的 commit 不在本地/远端任何祖先链上：停止登记，转协调或自行实现分支
- 单会话环境或登记簿无外来执行者记录：转入按审批回执自行实现的路径

## Verification
- merge-base --is-ancestor 确认实现 commit 是远端 main 的祖先
- 具名测试文件本地独立复跑通过（含应拦保持用例）
- 登记后回读登记簿记录确认 registered=True
- 任务收口所用 evidence 引用全部为系统铸造的 evidence:// 格式

## Counterexamples
- 单会话环境无协调面：登记簿无外来执行者记录，直接按审批回执自行实现，本方法只多花一次廉价查询
- 执行方声称的 commit 仍在未合并分支或与事实不符：不得登记，视为未完成
- 工作项是配置/策略翻转、无测试面：核验等于控制面状态加生效探针，而非跑测试
- 远端已含 commit 不等于已生效（部署未 rollout 时）：『推过』≠『已上线』，需另行比对部署面
