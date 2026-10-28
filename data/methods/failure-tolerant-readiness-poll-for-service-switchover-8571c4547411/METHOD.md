---
method_id: failure-tolerant-readiness-poll-for-service-switchover-8571c4547411
name: failure-tolerant-readiness-poll-for-service-switchover
description: 在单个脚本里同时做服务切换的变更（停旧进程→写守护配置→launchd 加载）和就绪轮询时，轮询探针在加载窗口内必然连接拒绝；若脚本带 set -e，第一拍 curl 失败（退出码7）就中断验证循环，产生貌似部署失败的回执，逼出额外一轮'哪些步骤实际完成'的诊断。本集预估加载12s实际约49s，说明固定 sleep 也不可靠。把'预期内的连接拒绝'当循环条件而非错误（until curl+sleep+超时上限），变更与验证分段；回执被截断时按已打印前缀判断完成步骤、直查真实状态，不重跑变更。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72b1f325-1293-4022-9fb8-46f58685873e:71:22bcd26cc3515caf7e17
evidence_refs: learning:learn:5bed3ce8302f
created_at: 2026-10-17T10:43:32.906276+08:00
updated_at: 2026-10-17T10:43:32.906276+08:00
---
## Trigger
需要把正在运行的裸进程切换为守护托管，或任何'停旧服务→拉起新服务→等就绪'的切换，且打算用一个 set -e 脚本一次完成变更+健康检查轮询

## Discriminator
写脚本时已从父进程命令行、端口监听记录与旧日志加载耗时（约12s）知道两件事：旧进程停掉后端口必然暂时无人监听、新进程就绪需要数十秒。因此探针连接拒绝是切换窗口内的预期状态而非异常——凡 set -e 脚本在启动序列后立即裸跑 curl 探测，第一拍必触发退出，且失败点在验证段而非变更段

## Short path
- 一次调用查清两个未知量：进程/etime/端口/健康检查回答'在跑吗'，父进程命令行+守护配置清单回答'有守护吗'
- 若同机存在同类服务的守护配置（如另一端口的 plist），直接沿该模板取 Environment/KeepAlive/日志路径，不凭空手写
- 变更与验证分离：写 plist→停旧→launchctl load 为一段；就绪轮询单独执行且容忍预期失败（until curl -sf; sleep N; 带超时上限），绝不让 set -e 保护预期会失败的探针
- 轮询等待期间用 launchctl list 的 pid 与上次退出码、日志推进情况区分'仍在加载'与'崩溃循环'
- 健康检查 OK 且新进程 ppid==1 且上次退出码为 0 即停止，对比切换前后引擎参数一致后收尾

## Stop conditions
- 健康端点返回正常且新进程父进程为 1（守护已接管）、上次退出码为 0，引擎参数与切换前一致
- 轮询超时上限已到，或 launchctl 显示非零退出码/无 pid——停止等待转排障，而不是无限重试

## Verification
- launchctl list 条目第1列有 pid、第2列上次退出码为 0
- 日志出现 serving/ready 行且时间戳晚于 launchctl 加载时间
- 健康检查返回与切换前逐项一致（同一模型、同一量化/引擎配置）

## Counterexamples
- 服务本应已就绪却仍连接拒绝（加载远超已知上界、或 launchctl 上次退出码非零）：此时拒绝是真实故障信号，不能用 || true 无限吞掉——容忍必须带超时和退出码检查
- 无就绪延迟的轻量操作（仅 reload 配置、探针立即应答）：set -e+立即探测并无害，无需拆分
- 失败发生在 launchctl load 本身（变更段而非验证段）：修复点在 plist/权限/路径，不在轮询写法
