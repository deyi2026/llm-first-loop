---
title: systemd Restart=on-failure 不覆盖干净退出，守护常驻服务要用 always
scenario: Linux 主机上以 systemd --user 守护 LFL web 服务；应用（uvicorn）在收到 SIGTERM 后优雅关闭超时并以 exit 0 退出
root_cause: ""
solution: "systemd 单元改用 Restart=always（不是 on-failure），保留 RestartSec=5s。判据：on-failure 只在失败/被信号杀死时重启，进程干净退出（exit 0）判 success → 不重启 → /health 000 且服务无声消失；显式 systemctl stop 属有意停止，always 同样不拉起，不影响升级流程。验收要覆盖两条路径：kill -9（崩溃）与 SIGTERM 后等应用自己退出（干净退出，约 20-40s 优雅关闭窗口，9s 内快照会误判为没退出）。当前性验证：执行 systemctl --user show lfl.service -p Restart，输出应为 always。复现：执行 kill -TERM $(systemctl --user show lfl.service -p MainPID --value)，等 40 秒后再查 systemctl --user show lfl.service -p MainPID -p NRestarts，MainPID 应换新、NRestarts 递增，且 curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8903/health 应为 200。"
evidence: "主机实测 2026-11-06：journalctl 有 \"Cancel 1 running task(s), timeout graceful shutdown exceeded\" + \"Main process exited\"，随后 systemctl inactive、/health 000、NRestarts 不变；改 Restart=always 后 SIGTERM→退出→systemd 换新 PID（206918→207350，NRestarts 1→2）、health=200；kill -9 场景同样自愈。"
tags: [systemd, Restart=always, uvicorn, 静默中断, linux]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-06T20:03:40.708777+08:00"
updated_at: "2026-11-06T20:03:40.708777+08:00"
---