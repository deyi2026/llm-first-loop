---
title: 嵌套 seatbelt 环境下 execute_command 全面失效（exit 71）时的可用/不可用执行通道盘点
scenario: "重启后的 LFL 会话中，execute_command 的每一次调用（shell 模式、argv 模式、后台模式、isolation 模式）都以退出码 71 失败，stderr 为 \"sandbox-exec: sandbox_apply: Operation not permitted\"。表现为命令根本没跑（连 pwd/echo/git --version 都失败），而非权限被拒。"
root_cause: ""
solution: "定位链：(1) 仓库自带 docs/REPORT-20261031-orchestration-gate-friction.md D5 已明确记载\"execute_command 自身运行在 seatbelt 内侧，任何内层 sandbox-exec 一律 sandbox_apply: Operation not permitted（退出码 71）\"，属已知环境结构限制而非本次改动引入；(2) 代码层根因在 src/llm_loop/tools/sandbox.py:_probe_sandbox_exec 只检查 sandbox-exec 二进制是否存在，darwin 上 auto 必然选中 sandbox-exec，不检测\"当前进程已在 seatbelt 内\"；(3) 沙箱模式来自进程 env EXEC_SANDBOX（llm_loop/config.py load_settings(env=os.environ)），进程启动后不可运行时更改，execute_command.py:892/973 前后台路径均无条件应用沙箱策略、无提权逃逸。通道盘点：可用=宿主侧裸 subprocess（review_admission 内部用 _git() 裸 git 冻结推送产物并由宿主签发 qualification；service_control publish 由宿主执行 git）；不可用=dsh_task（harness 自身 0.1s 崩溃，连\"回一行字符串\"都失败）、fix_loop（内部仍走 execute_command 同一条沙箱路径）、escalation（只绕灾难性硬阻断，不绕沙箱）、desktop_operate（终端明确只读拒绝）。结论：门禁与 push 必须由宿主沙箱外执行（用户 Terminal 或宿主脚本），模型侧能交付的是\"冻结产物+官方独立审查 PASS+精确命令\"。"
evidence: "execute_command 五次不同形态调用（shell/argv/isolation/后台/简单 echo）均 exit 71 + stderr \"sandbox-exec: sandbox_apply: Operation not permitted\"；read_file src/llm_loop/tools/sandbox.py 可见 _probe_sandbox_exec 仅做二进制存在性探测；read_file src/llm_loop/tools/builtin/execute_command.py:793-832/892 显示沙箱策略前后台均无条件应用；read_file src/llm_loop/config.py:992 显示 EXEC_SANDBOX 走 load_settings(env=os.environ)；dsh_task 两次调用均 0.1s 失败（stderr: Node.js v24.18.0）；fix_loop 报未启用且其 fix_loop.py:133 以 arguments={\"command\": check_command} 复用 execute_command；review_admission(kind=git_push) 成功返回 push_remote_commit=55b53ab8 与 candidate_sha256（宿主裸 git 路径可用）。"
tags: [execute_command, sandbox, seatbelt, exit-71, review_admission, 环境限制, 执行通道]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T22:42:58.404387+08:00"
updated_at: "2026-10-31T22:42:58.404387+08:00"
supersedes: [EXPERIENCE-20261031-exec-全线-eperm-auto-沙箱后端只探二进制存在-嵌套沙箱环境必然误判可用]
---