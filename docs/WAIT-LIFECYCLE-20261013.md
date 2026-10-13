# 主会话与后台任务等待契约

## 事故与范围

2026-10-13 主会话 `a2f05599-54ef-4df0-83ac-5403f3fbc184` 出现连续 17 次
`wait(seconds=118)`，累计请求 2006 秒，中间没有查询后台任务。墙钟等待正常返回，
但每次回执把单次时长标为「本会话累计」，主会话并未注入子代理预算载体。
会话取消也没有接入等待工具。后台测试采用 `pytest | tail ...; echo done`，
shell 的零退出码掩盖了测试进程失败。

原始会话、工具回执与后台任务记录仍为事实源；本文件只描述修复后的机械契约。
已验证的四条 RED 回归覆盖主会话累计、注册前 Stop、已完成 job 与管道失败。

## 等待能力

`wait(seconds=1..120, job_id=<可选>)` 等待发生在当前已授权 run 内，不调用模型、
不创建新 run、不签发新的自动续跑授权。

| 参数/条件 | 行为 |
| --- | --- |
| 省略 `job_id` | 只等墙钟；不监视后台任务 |
| 当前会话的 exact `job_id` | 已终态则立即返回；运行中由进程退出通知提前唤醒 |
| 达到 `seconds` | 返回 `wake_reason=timeout` 和 job 当前机械状态；不取消、不重跑 job |
| 当前 run Stop / 父取消 child | 返回 `wake_reason=cancelled`；其他资源的停止仍走既有 run 取消钩子 |
| 无权访问/不存在 | 如实失败；不跨会话查询 |
| 重启后只有 orphaned 事实 | 返回 `job_unobservable`；不重连 PID、不回收、不伪造终态 |

回执包含请求与实际时长、累计、`wake_reason`；job 等待另含 `state`、`exit`、
`local_handle`、`state_durable`。`completed/failed` 是进程终态，任务是否满足验收由模型
核验输出与要求。`killed` 若只有取消请求、尚未观察到退出，不视为进程已结算。

主会话每个 run 共享一个累计载体，跨工具派发和生成器 Context 恢复持续累加，
结束后恢复调用方 Context。它不套用 child 的 600 秒租约限额。未绑定 run 的直接
工具调用如实显示「累计未绑定」，不会伪造累计或租约。

child 继续使用既有 600 秒累计预算；在途等待先原子预留，结束/取消/异常后释放
预留并计入实际等待，防止并行调用重复花费同一剩余额度。已经结束的 job 无需等待，
不消耗预留预算。Stop 按 session + run_generation 归属，过期代次不能唤醒新代次。
当前 run 的取消状态检查补上「Stop 已受理但 wait 尚未注册」窗口。

## 验证命令退出码

`execute_command(..., fail_fast=true)` 显式使用 `bash -e -o pipefail`。
未处理的失败命令/管道以非零退出码终止后续串联步骤。`||`、条件判断等显式错误
处理仍按 Bash 语义执行。该选项不是所有子命令成功的证明，模型仍需核验日志。

默认 `fail_fast=false` 保留现有 shell 行为；默认 shell 零退出码只证明最终 shell
状态为零，不证明 `pytest | tail ...; echo done` 中的 pytest 成功。程序不解析命令
文本猜测任务意图，也不静默重写默认命令。

验证任务可按以下调用：

```json
{"command":".venv/bin/python -m pytest tests/unit/test_wait_main_lifecycle.py -q > data/wait-check.log 2>&1","run_in_background":true,"fail_fast":true,"workdir":"<项目工作目录>"}
```

用启动回执的 exact job_id 调用：

```json
{"seconds":120,"job_id":"<启动回执中的 job_id>"}
```

终态后用 `job_output` 读取退出码，再读取完整日志。需要延期的一次性续跑仍走
`schedule(wake=true)` 原有授权链；续跑中不能递归签发新授权。持续等当前 job 可以
用上述同 run 等待能力，无需放宽授权。

## 验证边界

测试覆盖真实主 run/Stop、Context 恢复、进程 watcher、失败退出码、超时、跨会话、
orphaned、取消代次隔离与并行 child 预算。候选必须独立审查后走项目完整门禁。
部署验证记录当前 generation、PID、源码/工具 Schema 和实际回执；旧服务的测试
结果不能替代新候选实际运行结果。重启先核验活跃会话，按正式服务控制流程排空。
