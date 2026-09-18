---
title: macOS 无 setsid：后台发射脚本需用 nohup/& 且校验日志已创建
scenario: "在 macOS 上通过 shell 定时/延迟启动维护脚本（如切换 launchd 服务、重启本地模型服务），常见写法 setsid nohup cmd & 在 Linux 可用但 macOS 不带 setsid，报错被 >/dev/null 2>&1 吞掉后 echo \"fired\" 仍输出，造成脚本已执行的假象。"
root_cause: macOS（Darwin）默认不带 util-linux 的 setsid；`setsid nohup ... &` 中 setsid 不存在导致整条命令失败，但错误被重定向吞掉，后台化使退出码也不可见。
solution: "macOS 上直接用 `nohup bash script.sh </dev/null >/dev/null 2>&1 &` 发射；发射后立刻 sleep 2-3 并 cat 目标日志确认出现脚本首行（如 \"switch start\"），用日志存在性而非 echo 输出判定是否真正启动。若脚本自带 exec >> log 2>&1，更可靠。"
evidence: ""
tags: [macOS, launchd, nohup, setsid, 后台任务, 静默失败]
source: {}
status: invalid
created_at: "2026-09-11T08:44:56.462938+08:00"
updated_at: "2026-09-11T14:11:48.726933+08:00"
---