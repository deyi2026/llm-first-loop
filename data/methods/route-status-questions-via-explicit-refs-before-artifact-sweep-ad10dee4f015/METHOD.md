---
method_id: route-status-questions-via-explicit-refs-before-artifact-sweep-ad10dee4f015
name: route-status-questions-via-explicit-refs-before-artifact-sweep
description: 当用户追问任务状态（完成没？为何没被唤醒？）而会话事件流/回执中已出现显式引用（interop notify 的 from/ref、后台 job id、失败测试名、git status 未提交变更集）时，先按 ref 定向查询权威记录逐个子问题作答，再考虑枚举文件系统工件；对验证失败先在干净基线复现定归属，再沿文件 git log / 规则 ID 溯源到外部进行中工作，最后只精确提交自己的路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:946:6e9a1423070d68022ce9
evidence_refs: learning:learn:213897c1bfb5
created_at: 2026-09-23T14:51:17.426308+00:00
updated_at: 2026-09-23T14:51:17.426308+00:00
---
## Trigger
会话恢复或用户追问任务状态时，事件流/回执中已可见与问题直接对应的显式 ref（调度器 notify ref、job id、失败测试名、未提交文件清单），而下一候选动作是继续扫目录或读旁路工件（如其他工作流的测试输出目录）

## Discriminator
事件流条目已给出 interop.notify 的 from=lfl-scheduler;ref=<sched-id> 与 from=job-registry;ref=<job-id>（prompt_chars=0），且 git status 已列出本任务未提交的精确文件集——这两类显式引用把『为何没唤醒』缩成查该 sched ref 的投递状态记录、把『完成没』缩成读该 job 回执与失败清单，无需枚举 tmp/测试工件目录

## Short path
- 读会话事件流，为每个子问题提取对应显式 ref：唤醒问题→scheduler notify ref；完成问题→job ref + git status 变更集
- 按 sched ref 定向查记录，得到投递状态（如 awaiting_user_authorization），直接回答唤醒问题
- 读 job 回执取得全量失败清单与失败测试名；未知量：失败是否由本变更集引入
- 先单独复跑失败测试取细节，再 stash 工作树在干净 HEAD 复跑同一组测试定归属
- 对确认预存的失败沿 provenance 溯源（该文件的 git log 提交信息、规则 ID 全局检索）归因到外部 WIP 或其他演进
- 精确 add 自己的路径提交；登记被状态机拒绝时按既有 CLI 通道处理，预存问题移交对应工作流而不顺手代改

## Stop conditions
- 每个用户子问题均已由显式 ref 指向的权威记录回答（投递状态、全量失败清单）
- 全部失败已在干净基线复现并归因到非本变更集来源
- 本变更集已按精确路径提交且未混入任何旁路文件，预存问题已移交而非顺手修改

## Verification
- 按 ref 查到的记录与事件流条目的 id/ref 一致且时间顺序吻合
- 干净 HEAD 复现的失败集合与当前工作树完全相同（数量与测试名一一对应）
- 提交 diff 仅含本任务文件，预存失败在本次提交中未被顺手改动

## Counterexamples
- 事件流中不存在任何相关显式 ref（调度器根本未触发、无 job id）时，枚举日志/目录做宽发现是正确下一步，不应套用本方法
- 用户问题本身关于工件内容（如『这些测试结果文件说了什么』）时必须直接读工件，ref 路由不适用
- ref 指向的记录缺少所需事实（查无 pending 状态记录）时应扩大到目录/日志搜索，而不是反复换参数查同一 ref
- 失败在干净 HEAD 上不复现时归属判断反转：必须先修自己的变更再提交，不能按预存处理放行
