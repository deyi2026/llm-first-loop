---
method_id: free-owned-services-by-held-port-pid-verify-endpoints-f770ffaa10c5
name: free-owned-services-by-held-port-pid-verify-endpoints
description: 用户要求释放不再使用的模型服务内存时，若这些服务是本任务先前自己启动的，不要先跑系统级进程枚举（top/ps 类在内存压力下恰是最慢或被拒的工具）——直接用已持有的 port→PID 映射，按剩余需求分区后 kill：已完成测试的先停，剩余工作还需要的（如最后一个数据点）用完再停。验证只用两个廉价端点计数：目标端口 listeners=0（同时覆盖 wrapper 自动重启）与 vm_stat free pages 前后对比；sweep 中遇到非自有服务显式排除。
aliases: 把跑完的推理服务停掉腾内存, 清理闲置模型进程释放内存, top 被拒或命令超时时怎么定位占用, 杀模型服务前先确认是自己起的, 按端口杀进程并确认没有自动重启
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:3caec2da-e2d5-42be-80d2-60268ec4cecb:234:267a209b7585fe377198
evidence_refs: learning:learn:a84e3049a930
created_at: 2026-11-01T20:11:00.878485+08:00
updated_at: 2026-11-01T20:11:00.878485+08:00
---
## Trigger
用户要求清理/释放闲置模型服务或后台推理进程占用的内存（或内存压力已导致命令超时），且这些服务的端口/PID/完成度属于本任务已持有的 provenance。

## Discriminator
任务状态里已有 port→PID→完成度 映射，且一次廉价 vm_stat 已确认压力真实（free pages 极低）——此时再跑 top/ps 类系统枚举不产生新信息只会超时/被拒；执行释放所需的全部句柄已经在手。

## Short path
- 按剩余需求给自有服务分区：已完成测试的列入立即释放，剩余工作尚需的标记为'用完即释'。
- 对已完成服务直接 kill 其已知 PID，并在同一命令内 sleep 2-3s 后检查这些端口 listeners=0（覆盖 wrapper 自动重启），不跑 top/ps。
- 用 vm_stat free pages 与释放前对比，确认内存真实回收并给出量化数字。
- 继续用仍加载的服务完成剩余工作；结束后同法 kill 并同样验证。
- 检查中遇到非自有服务（用户自己的项目）显式排除并说明，不纳入清理。

## Stop conditions
- 待释放端口全部 listeners=0 且 free pages 回升到预期量级，释放目标即达成。
- 剩余工作所需服务已完成其最后消费，并以同一程序释放并验证完毕。
- 发现某端口属用户/系统自有进程，立即将其移出 kill 名单。

## Verification
- kill 后检查目标端口 listeners=0，而不是重跑 top 做全局枚举。
- vm_stat free pages 释放前后对比，量化回收量。
- PID 若来自较早会话或时间较久，kill 前先 ps -p <pid> 确认命令行仍属目标服务，防 PID 复用误杀。

## Counterexamples
- 不知道占用者是谁（孤儿进程、上次会话遗留）：必须先做 ps/lsof 发现，凭猜测直接 kill 反而危险。
- 用户问的是'为什么内存低/谁在占用'：诊断本身就是交付物，不能跳过测量。
- 服务由 supervisor 托管且需优雅停止或有未落盘状态：须改为经管理层停启，而非裸 kill。
- 超时根因并非内存压力（如网络阻塞）：跳过诊断会错误归因。
