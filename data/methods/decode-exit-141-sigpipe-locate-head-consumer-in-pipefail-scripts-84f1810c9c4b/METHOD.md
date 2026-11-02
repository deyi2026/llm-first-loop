---
method_id: decode-exit-141-sigpipe-locate-head-consumer-in-pipefail-scripts-84f1810c9c4b
name: decode-exit-141-sigpipe-locate-head-consumer-in-pipefail-scripts
description: 带 set -euo pipefail 的守护/定时脚本以 exit 141 且无任何日志或状态产物的方式死亡（表现为“从未运行过”）时，先把退出码机械解码为信号（141-128=SIGPIPE），再在已读过的脚本正文里 grep 早退消费者（head/grep -m）定位崩溃管道，而不是先加执行轨迹或二分。典型根因：find|head|sed 中 head 读满即退，find 收 SIGPIPE 返回 141，pipefail 把它传播给整条命令替换，set -e 在首次写日志前杀掉脚本。修复是把截断移到管道末段（producer|sed -n '1,20p'）或对该处局部关 pipefail，重跑一次并确认此前缺失的日志/flag 真的出现。
aliases: 退出码141什么意思, 脚本141静默崩了没日志, find head SIGPIPE 脚本死, 守护脚本像从来没跑过, 退出码减128看信号, pipefail 传播 SIGPIPE 排查
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:40d20564-ac46-4792-b62c-f0b083523714:296:2c6973c9da823caa4223
evidence_refs: learning:learn:9a2e082bbd17
created_at: 2026-11-01T23:09:16.817835+08:00
updated_at: 2026-11-01T23:09:16.817835+08:00
---
## Trigger
set -e 且 set -o pipefail 的 shell 脚本（launchd/cron 守护、巡检脚本）单次执行返回 exit 141，且预期日志/flag/状态文件一条都没写；或一个长周期静默的守护被怀疑“从未运行”，而历史退出码记录为 141。

## Discriminator
141 = 128+13 = SIGPIPE；结合脚本已可见的结构事实——存在 producer（find/长流输出）接早退消费者（head -N、grep -m）的管道，且 pipefail 会把中段非零传播给整条命令替换——即可把死因从“几百行任意位置”缩到“这类管道所在分支”，且该分支位于首次写日志之前正好解释零产物。

## Short path
- 对静默死亡的退出码先做机械解码：exit≥128 → 减 128 → 信号名（141→SIGPIPE，137→SIGKILL，143→SIGTERM），不先加 trace。
- 在已读过的脚本正文里 grep 早退消费者与管道符的组合（head -N、grep -m），定位含 producer|head 的指纹/巡检分支。
- 确认该分支位于首次写日志/状态文件之前——解释“无任何产物、像从未运行”。
- 修复：把截断移到管道末段（find | sed | sed -n '1,20p'）或对该命令替换局部关 pipefail；其余 set -e 语义不动；bash -n 通过。
- 以真实调度方式重跑一次：exit 0 且此前缺失的日志行/flag 真实出现即完成验证。

## Stop conditions
- 重跑单次执行 exit=0，且此前为空的日志/状态产物本轮真实生成。
- 退出码不属于信号族（<128），或日志已写到某条——本卡的“零输出”判别不成立，改从最后一条日志锚点续查。

## Verification
- bash -n 通过后，用与生产一致的调用方式（launchd 加载或 once 模式）重跑一次，核对退出码与本轮新日志时间戳。
- 确认修改只移动了截断位置或加了局部 pipefail 豁免，脚本头部 set -euo pipefail 整体语义未被移除。

## Counterexamples
- 调用方自己写 cmd | head 时收到 141 是良性噪音（head 正常早退），不是被调脚本 bug。
- 脚本没有开 pipefail：producer 的 141 被管道末段命令掩盖，脚本不会死在那里，141 另有来源（如自身 stdout 被外层关闭）。
- exit 141 但日志已写到某点：死点在更后面，空输出判别不成立。
- exit 0 却缺产物属于掩盖型失败（如 | tail 吞错），应走回执正文核验，不适用本卡。
