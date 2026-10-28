---
method_id: scope-source-receipt-first-premise-test-then-partial-execute-3b7faeedc76f
name: scope-source-receipt-first-premise-test-then-partial-execute
description: 执行上一轮多步建议时，先测条件式停用/回滚条目的承载前提（如『该开关空转、关掉零损失』）再动手：优先用一次运行态权威回执（控制面 status 逐 scope 的激活位与配置来源标注，如 scope_sources 指向 runtime_toml_service:web）一步证实或证伪；证伪则跳过该条目、其余条目照常执行，并在交付报告最前显式更正，把该条目的决定权交回计划所有者。只有不存在此类回执时才退到最短代码链（flag 消费点→共享装配函数→服务入口是否走该装配），避免为回答『开关是否活着』做多轮入口考古。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:f6f1dadc-64d2-4789-bbac-44b68f133442:1505:db35e9a5dc02b0774063
evidence_refs: learning:learn:8c2fcc5ea9fb
created_at: 2026-10-20T09:27:00.549683+08:00
updated_at: 2026-10-20T09:27:00.549683+08:00
---
## Trigger
用户要求『按建议/按计划执行』上一轮产出的多项建议，其中至少一条是条件式停用/回滚/删除类动作，且其正当性建立在早前断言的事实前提（『无用/空转/零损失』）上；执行环境存在可一次调用取得、逐 scope 标注激活状态与配置来源的运行态回执。

## Discriminator
回执是否已把目标 scope 标为激活且来源指向所议配置节（例如 semantic_scope_sources={"method":"runtime_toml_service:web"}），或配置文件自身带带日期的授权激活记录与实测数据；二者任一在场即可一步证伪『空开关』前提，无需全量 consumer 考古。

## Short path
- 锚定执行前状态：git status/diff、待提交改动、目标配置节原文
- 对每个条件式条目列出其承载前提，先测前提再动手：一次调用取运行态 status 回执，核对目标 scope 的激活位与 scope 来源标注
- 回执显示该机制在目标服务已激活且来源即所议配置节 → 前提被证伪：跳过该条目，该配置一个字不改
- 按原计划执行其余仍成立条目（提交/门禁/推送/部署）
- 报告把证伪放在最前：引用回执加一两个代码佐证（flag 消费点均在共享装配函数、服务入口确走该装配），说明为何未执行，并给出『若仍要执行只需一行配置+重启』的边界

## Stop conditions
- 回执已明确回答目标 scope 的激活与来源，且有一个独立佐证一致，即停止验证，不再枚举更多 usage 或入口
- 前提未被证伪且其余条目已执行完毕、门禁通过

## Verification
- 回执中 scope 激活位与 scope_sources 指向的配置节一致
- 一次定向 grep 确认 flag 消费点全部位于共享装配函数，且目标服务入口确实调用该装配，不做全库宽搜
- 最终报告显式包含：未执行条目、证伪证据、以及恢复执行该条目所需的最小操作

## Counterexamples
- 前提是质量/危害判断而非激活判断：回执只能证明开关活着，不能证明它有益或有害，需要效果测量而非 liveness 回执
- 执行环境不存在逐 scope 来源标注的回执（只有进程表/零散日志）：消费点→装配→入口的最短代码链才是必要路径
- 前提在执行时仍为真（该机制确实无任何服务消费）：直接执行停用即可
- 条目是无前提的用户直接明令（『关掉它』）：先按命令执行，事后质疑，而不是扣住不执行
