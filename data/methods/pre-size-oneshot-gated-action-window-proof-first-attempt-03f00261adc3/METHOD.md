---
method_id: pre-size-oneshot-gated-action-window-proof-first-attempt-03f00261adc3
name: pre-size-oneshot-gated-action-window-proof-first-attempt
description: 拿到稀缺准入（如审查 PASS）后执行受保护的一次性命令（如 git push）前，先用不被护栏拦截的只读命令测量动作规模（待推对象数/包字节），估计能否在工具时间窗内完成；可能超窗则首次尝试就用单命令后台+日志的窗口免疫模式，并以独立真值源核对终态。本集教训：前台首推 60s 超时即烧掉资格，后台重试又被拒，被迫重铸昂贵审查；且资格按产物 SHA 绑定，并发提交移动 HEAD 也会使其失效，串行重试只烧预算。
aliases: push 超时把准入资格烧了, 审查通过后推送还是失败, 一次性授权命令先估耗时, 大 push 撞上工具超时上限, PASS 之后资格失效重试被拦, 推不动先量一下要推多少
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:fb85cea0-beb4-424d-b482-2819180ee46f:1851:c15f73ca2712e03ebe5e
evidence_refs: learning:learn:328ed6d5e8f2
created_at: 2026-11-01T11:54:05.610017+08:00
updated_at: 2026-11-01T11:54:05.610017+08:00
---
## Trigger
持有昂贵、难重铸的授权/资格（审查 PASS、一次性准入）要执行受保护命令，且执行环境对该命令存在硬时间窗（工具超时上限），而动作规模尚未测量但可用只读命令测出

## Discriminator
授权重铸成本已在会话中显性化（每轮审查约4-5分钟、已消耗多轮），且动作重量（对象数/字节数）可在花掉授权之前用护栏不拦截的只读 git 命令测得；超时或并发 HEAD 移动任一发生都会使资格作废

## Short path
- 花授权前先只读测规模：git rev-list --objects 远端基线..HEAD | wc -l 与 count-objects -v 得对象数/包字节，解决『一个时间窗内能否完成』这个未知量
- 规模可能超窗 → 首次尝试即用单命令后台模式（重定向日志文件），护栏通常只禁复合命令不禁后台
- 轮询日志并用独立真值源（git ls-remote 比对远端分支 SHA）核对终态，禁止以重跑命令代替验证
- 若已超时且远端未变：先只读诊断失败类别（传输慢 vs 并发提交移动 HEAD 使资格 SHA 失配），不立即重跑
- 并发写者活跃导致资格反复作废时，停止串行重审，转静默窗口协调（请用户暂停并发会话）或分段 refspec 推送

## Stop conditions
- 独立真值源显示目标已达成（远端分支 SHA == 本地 HEAD）
- 资格失效且根因为并发 HEAD 移动：不再自行重试，升级为用户决策
- 测量显示动作规模远小于时间窗：直接前台单命令执行后验证即可

## Verification
- push 类终态用 git ls-remote 比对远端 SHA，不信任本地退出码或横幅文本
- 后台模式检查日志文件中的退出码与传输统计
- 重试前核对资格绑定维度（产物 SHA/目标/父会话）仍与当前一致

## Counterexamples
- 小推送（少数小 commit、几百 KB）：预测量纯属浪费，前台直接执行加一次终态核对即可
- 授权廉价可随时重取（幂等 token、无审查预算约束）：超时-重试循环成本低，无需预测量
- 护栏明令禁止后台/异步执行受保护命令：正确做法是分段 refspec 或申请更长窗口，而非后台化
- 目标动作本身只读且不消耗任何授权：不适用
