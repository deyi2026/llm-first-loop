---
title: macOS pgrep -f 对活进程可选择性全盲——进程探针与 launchd 辅助脚本的端口定源不可依赖默认环境
scenario: 在 macOS 上用 pgrep -f 构建服务停止/判活探针（守护、重启脚本、CI 进程清理），或 launchd 拉起的辅助脚本依赖 shell 默认端口/继承环境。
root_cause: ""
solution: "进程定位一律用 ps -eo pid=,command= + 锚定项目路径的 ERE（或 lsof 端口反查 + ps 命令行校验），不要用 pgrep -f 做生命周期权威；launchd 环境下端口/路径等业务配置必须经工作区配置权威（resolver/.env）定源，不得依赖脚本内置默认值或继承环境。测试若以 stub pgrep 验证探针，无法覆盖此故障面——需在真机对真实进程做一次探针冒烟。"
evidence: "evidence://v1/6e88f60d055abbe4bb8af8bd57076ed1874c27ae013684541c40ee776509ef5e（pgrep -fl launch 列表缺 53802）；本会话 execute_command 回执：pgrep 三种模式对 53802 全空 + ps-grep 命中（command#2c787b5e4cf4 同轮）；ps -p 53802 -ww -o command= | od -c argv 干净；pgrep -f mirror/.venv 列出 11 进程不含 53802；launchctl getenv WEB_PORT 空；lsof 8903 LISTEN 53802；cat data/web.pid=50078（陈旧）vs live 53802。"
tags: [macos, pgrep, process-probe, launchd, restart-system, port-authority, guard]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-24T14:06:30.057462+08:00"
updated_at: "2026-09-24T14:06:30.057462+08:00"
---

实证（2026-09-24，llm-first-loop-mirror）：
1) 活着的 web 进程 PID 53802（argv: /path/.venv/bin/python -m llm_loop.runtime.launch web，od -c 确认干净、ps/lsof/service_control 全可见）对 pgrep -f 全面不可见：带 $ 锚模式、去锚全路径模式、去锚子串模式、宽匹配 'mirror/.venv'（该宽匹配列出其他 11 个镜像 venv 进程唯独不含它）全部 miss。同 argv 形状的兄弟进程 feishu/learning pgrep 可见 → 可见性是实例级运气，不是契约。
2) ps flags 差异：53802=0x4044，兄弟=0x4004（多 0x40 位），机制未定论；不影响工程结论。
3) 次生坑：launchd 用户域无 WEB_PORT（launchctl getenv 空）→ 守护直调 restart_system.sh 时用脚本默认 8902，而真实端口 8903 来自 .env/runtime.toml（进程内 load_env_file 定源）。脚本级端口逻辑（stop 端口兜底/start 冲突检查/curl 健康）全部落错端口。runtime.resolver 以 rc=0 返回空串的坑已在 restart_mirror.sh:240 注释记载。