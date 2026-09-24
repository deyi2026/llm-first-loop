---
title: 工具暂态超时诊断：readonly 池阻塞 vs 组件慢 vs 进程 hang 的三向排除法
scenario: LFL 会话中 architecture_status 多次 60s 超时，同期 search_files 也超时，而 execute_command/service_control/event_stream 正常
root_cause: ""
solution: 不要先猜工具 bug。按序：(1) event_stream 确认超时调用轨迹；(2) 读 registry.py 分类：卡死工具是否同属 _READONLY_TOOLS 4-worker 池而正常工具走独立路径；(3) 独立进程逐组件计时排除组件本身；(4) curl web HTTP 判定服务进程是否 hang；(5) 对比 service_control pid/git_head/started_at 变化识别外部并发 checkout+重启窗口；(6) 间隔重试确认暂态。
evidence: "evidence://v1/bf784172a97bc2708bfa849130049a6ad6e40ff9bd5593f38913d45825aeeeb2（组件计时全<0.1s）；evidence://v1/6eb955a8dcf359781f45a07ea172db2fea36df8bc9f7de8eec536ead82c57a78（web HTTP 3ms 健康）；service_control status 回执 pid=14289/started 21:48:12+0800/git_head=b3f31b7f 与上轮 36748/2a714e4e 差异；architecture_status 重试成功回执"
tags: [tool-timeout, transient, readonly-pool, concurrent-restart, diagnosis]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-22T22:08:32.568105+08:00"
updated_at: "2026-09-22T22:08:32.568105+08:00"
---

诊断路径（本次验证有效）：
1. 事件流(event_stream)确认超时调用确实发生且无异常登记；
2. 读 registry.py 确认超时工具与正常工具的执行池归属差异：_READONLY_TOOLS 4-worker 线程池 vs execute_command 独立进程；
3. 独立进程计时复现：load_settings() 后逐组件计时——若组件 <0.1s 则排除组件本身；
4. web HTTP 侧探测（curl -w time_total）区分 web 进程 hang 与执行池阻塞；
5. 间隔重试验证暂态；service_control status 对比 pid/git_head/started_at 变化锁定外部并发操作窗口。
根因类型判定：web 进程 git_head 在诊断窗口内从 2a714e4e 变为 b3f31b7f 且 pid 更换（36748→14289, started 21:48 +0800）= 另一会话 git checkout + 直连重启，readonly 工具依赖的文件/进程检查被 checkout I/O 拖慢排队。