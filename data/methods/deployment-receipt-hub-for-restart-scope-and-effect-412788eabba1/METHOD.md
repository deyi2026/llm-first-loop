---
method_id: deployment-receipt-hub-for-restart-scope-and-effect-412788eabba1
name: deployment-receipt-hub-for-restart-scope-and-effect
description: 回答『变更要重启才生效吗/这次重启会带上哪些更新』时，把一份 desired-state 部署状态回执当唯一 provenance 枢纽：runtime_root 直接钉死仓库（不做路径猜测或同名目录枚举）；本次重启携带集=live_head..desired_git_head 差集，部署绑定 head 是上界，远端 main tip 是另一个问题须单查并显式声明排除；restart_required 只是线索，既往 action_id 必须查终态（受理≠完成，failed 的 detail 自带 remediation）；『已生效』的终审用线上实际服务产物指纹（served 文件与新旧 release 目录比对+变更特有 marker 命中数），不信标志位。受理新动作后即止，下轮查终态，不阻塞等待。
aliases: 改完了要不要重启才生效, 这次重启会捎带哪些提交, 上次重启到底成没成, 怎么确认线上已经换到新版本, 部署状态里一次拿全仓库和版本
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1ee6738f-0a1e-46fa-9522-fd9f35a8933a:783:c30d30788aea64c7e20e
evidence_refs: learning:learn:26176441e1a7
created_at: 2026-10-27T23:14:59.418449+08:00
updated_at: 2026-10-27T23:14:59.418449+08:00
---
## Trigger
用户问某已提交/已构建的变更『需要重启才生效吗』或『这次重启会一起带上哪些别的更新』，且环境存在 desired-state 部署控制面（service_control/status 类回执）可一次获取

## Discriminator
回执里是否同时携带 live git_heads、desired 绑定（generation/git_head）、restart_required、runtime_root/code_root 与既往 action_id——这些字段已把『要不要重启、带什么、去哪个仓库看、上次动作成没成』一次缩到可差集/可查终态的程度；缺的只是对回执做定向抽取（search/分段 hydrate），而不是文件系统定位与目录枚举

## Short path
- 读一次部署状态回执，用定向检索/分段 hydrate 抽取 runtime_root、live heads、desired git_head、restart_required、既往 action_id
- 按 action_id 查既往重启终态：受理≠完成；failed 的 detail（busy/run locks 等）即 remediation 输入
- 在回执给出的 runtime_root 仓库做 live_head..desired_git_head 差集=本次重启携带集；另查权威远端 main tip，逐条列出 tip 之上、desired 之外的提交并声明不在本次 generation 产物内
- 用线上实际服务产物指纹终裁生效与否：served bundle 引用与新旧 release 目录文件比对 + 变更特有 marker 命中数（旧 0/新 1）
- 未生效且既往动作 failed 则重新发起 restart，记录 action_id 即止，下轮查终态闭合

## Stop conditions
- live head==desired git_head 且 served 产物指纹命中新 release 的变更 marker → 已生效，回答无需重启并停止
- 携带集与远端增量均已逐条列明、新 action 已受理拿到 action_id → 本轮停止，留待下轮终态核对

## Verification
- served 产物文件（文件名/sha）与所指 release 目录内文件一致，marker 命中数与预期相符
- 携带集提交数与 desired 绑定 head 对账闭合；远端额外提交均确认不在当前 generation 产物内

## Counterexamples
- 状态回执只有布尔标志、无 head/路径绑定字段 → 差集与仓库定位不可得，退回 mtime 对齐或按进程启动 head 做祖先测试
- 变更是运行时数据/配置而非构建产物 → bundle 无 marker，生效裁决移到存储/读取端点，不用产物指纹
- 无 desired-state 控制面的裸进程部署 → 回执枢纽不存在，才需要进程考古与文件系统枚举
- 既往无任何 action、属首次发布 → 无终态可查，直接进入发起与受理
