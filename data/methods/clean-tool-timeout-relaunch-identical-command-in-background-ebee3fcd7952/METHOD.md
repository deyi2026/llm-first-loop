---
method_id: clean-tool-timeout-relaunch-identical-command-in-background-ebee3fcd7952
name: clean-tool-timeout-relaunch-identical-command-in-background
description: 前台命令被工具执行上限拦下：回执只有『超过 Ns 未完成』，无报错、无 usage 错误。这种干净超时本身已验证调用方式（参数若不被接受会在秒级报 usage 错而非耗满时限），唯一未知量是总时长。正确动作是把逐字相同的命令转后台 job 并阻塞等到终态，而不是回头 grep/重读源码确认参数。等待期判活看 state 字段：stdout 进管道后被块缓冲，查询持续 0 行不代表卡死；终态后凭 exit code 加产物文件（大小/hash/内容）双重验证再交付。
aliases: 渲染跑一半被限时杀掉怎么办, 被60秒截断是写错了还是单纯太慢, 等很久一行输出都没有是不是挂了, 超时之后还要不要先看脚本, 怎么让长跑任务实时报进度
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:99da05c7-a192-45a5-8e59-65ef85eb2c1e:119:433b04271330c6ed5d3e
evidence_refs: learning:learn:bcddd68e023f
created_at: 2026-11-04T22:32:48.746139+08:00
updated_at: 2026-11-04T22:32:48.746139+08:00
---
## Trigger
前台执行一条已组装好的命令，工具回执为执行时限超时（如『超过 60s 未完成』），且无 traceback、无 usage 错误、无错误输出，进程原本在正常推进

## Discriminator
超时回执是否『干净』：只有时限到期这一事实，没有任何错误签名。干净超时 = 调用方式已被这次运行验证，剩余未知量从『命令对不对』缩成『总共要跑多久』，后者只能靠跑更久解决，不能靠读代码解决

## Short path
- 用目标参数前台执行一次；未知量：调用是否成立、耗时是否在工具时限内
- 若回执为干净时限超时：判定调用已验证、剩余未知量只有总时长；不重读脚本/配置去『确认参数』
- 以逐字相同的命令启动后台 job；未知量：完整耗时与最终退出码
- 阻塞 wait 至终态；期间判活只看 state 字段（管道块缓冲下查询 0 行不是死亡证据），不取消不重启
- 终态后验证产物文件本身（存在、尺寸/hash、内容识别），与退出码交叉印证后交付，停止

## Stop conditions
- 后台 job 终态 exit=0 且产物文件通过独立内容验证（而非只信退出码）
- 超时回执含 traceback/usage 错误/非零退出 → 转故障诊断分支，本方法终止
- 预计总耗时远超任何可等待预算 → 先降规格小样估时，再决定执行形态，不直接押后台

## Verification
- 后台命令与前台被掐断的命令逐字一致（是转后台，不是重新猜参数）
- 退出码为 0 且产物文件大小/hash/内容均符合预期，二者交叉印证
- 等待期间未把『输出 0 行』当作卡死证据而取消或重启正常推进的任务

## Counterexamples
- 回执带 traceback、argparse usage 错误或非零退出：这是真故障，后台重跑同一命令只会重复失败
- 命令阻塞在 stdin/网络等待（挂起而非慢速推进）：后台化只是把挂起挪到看不见的地方，需要输入重定向或命令自身的超时参数
- 运行时长无上界或远超轮询预算（如全量大规模计算）：应先小规格基准估时再选执行形态
- 输出 0 行且 state 已是 failed/cancelled：这是终态失败，不能再按『缓冲假象』继续等
