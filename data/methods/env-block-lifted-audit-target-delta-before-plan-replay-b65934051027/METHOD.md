---
method_id: env-block-lifted-audit-target-delta-before-plan-replay-b65934051027
name: env-block-lifted-audit-target-delta-before-plan-replay
description: 环境类阻塞（目标只读/EPERM/allow_list 拒绝）解除后，blocked 任务书是过期假设而非待执行清单：阻塞窗口里外部行为者可能已把部分工作做完（本集 P0 首提交即由外部完成）。恢复后第一个未知量是『工作是否仍未做』，答案在目标自身的权威现状（git log/status、已存在产物），不在旧会话预演产物或 evidence 库换词检索。先读目标现状，把任务收缩成差量再执行；要登记的事实从目标自身元数据（嵌套 .git、CMakeCache）取真值。
aliases: 解禁后先看目标现状再干活, 别人可能已经把活干完了，先查最新提交, 只读解除后旧任务清单可能过期, 续做被卡任务前先对一次账, 别急着重放上次的预演脚本, 恢复写权限后先找外部新提交
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:40d20564-ac46-4792-b62c-f0b083523714:168:e67ec5720b7345b462d6
evidence_refs: learning:learn:f3f52c396179
created_at: 2026-11-01T22:50:39.088396+08:00
updated_at: 2026-11-01T22:50:39.088396+08:00
---
## Trigger
任务因会话级环境约束（目标只读、EPERM、子代理 allow_list 拒绝）被记录为 blocked；随后约束被解除（外部重启换进程代、权限恢复），准备继续执行原任务书。

## Discriminator
blocked 原因文本只描述环境不描述工作内容，且解除动作由外部执行者完成（外部终端 restart、新 generation），同时存在并行会话/外部终端——这三点在恢复时点已可见，足以判定阻塞窗口内目标可能被外部改动，任务书前提需先复核而非直接重放。

## Short path
- 最小探针确认阻塞解除：一次写探针（touch+rm）即可，不重验整条继承链
- 立刻读目标自身权威现状：git status + log -1（+相关目录存在性），回答唯一先决未知量：任务是否仍未做
- 外部已完成的部分（如首提交已存在）从执行清单划掉，剩余范围重定义为差量；不重放旧会话预演脚本、不在 evidence/archive 库反复换措辞找旧方案
- 执行差量时，要写进记录的事实从目标自身元数据取真值：vendored 副本读嵌套 .git 的 remote/HEAD/status/stash，构建参数读 CMakeCache
- 提交后以工作树干净 + 提交链与任务条目一一映射作为完成证据

## Stop conditions
- 目标现状证明某任务条目已被外部完成：从清单划掉，只登记核实结论
- 剩余差量全部落地且工作树干净、提交可核验
- 外部改动与任务书结构性冲突（做了但方式不同）：停下等裁决，不强行叠加

## Verification
- 外部提交与任务书逐条映射：哪些已做、哪些剩，逐条有 git 证据
- 溯源/登记文档中的每个事实都能指回目标自身元数据（commit sha、remote、CMakeCache 键值），无凭记忆或脚本注释的断言
- 最终 git status 0 条、提交链完整

## Counterexamples
- 阻塞原因是内容性的（等上游决策、等数据到位）：解除后世界不会漂移，按原计划直接继续，深审计只增加延迟
- 单一行为者、无并行会话或外部终端的环境：阻塞窗口内外部改动概率极低，一次轻量 freshness 检查即可
- 幂等且自包含的重放（如重跑一次测试套件）：无共享状态冲突，重放即正确
