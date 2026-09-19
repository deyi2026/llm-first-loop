---
title: 镜像 LFL 配置独立飞书桥：凭证隔离 + 脚本精确匹配 + PYTHONPATH 注入
scenario: "给镜像工作区（llm-first-loop-mirror）配置独立飞书桥，硬约束：主区（llm-first-loop）已在用的飞书桥零接触。镜像与主区共享 .venv（符号链接），editable 安装指向主区 src；两区 restart 脚本用 pgrep -f \"llm_loop.feishu\" 定位进程（命令行相同会互相误匹配）。"
root_cause: ①pgrep -f 匹配完整命令行，主/镜像进程命令行字符串相同（仅 .venv 符号链接路径前缀不同）→ 镜像脚本会把主区进程误判为自己，stop 即误杀主区桥；②共享 venv 的 editable 安装（__editable__.llm_first_loop-*.pth）指向主区 src → 不带 PYTHONPATH 镜像进程加载主区代码；③restart_feishu.sh 的 _load_llm 只读环境变量不读 .env。
solution: "1) 凭证隔离：镜像独立飞书 app 凭证写入镜像 .feishu.env（600 权限 + gitignore），覆盖 rsync 同步来的主区凭证副本；token 预检用 POST open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal（code=0 即有效，无副作用）。2) 脚本修复：restart_feishu.sh / restart_system.sh 的 pgrep 加工作区路径前缀精确匹配（pgrep -f \"$PROJECT_DIR/.venv/bin/python -m llm_loop.feishu\"），防 stop/restart 误杀主区桥。3) PYTHONPATH 注入：_start_service/_start 中 export PYTHONPATH=\"${PROJECT_DIR}/src${PYTHONPATH:+:$PYTHONPATH}\"（MIRROR 协议 §3：共享 venv editable 指向主区 src，不带则加载主区代码）。4) 启动走 restart_system.sh feishu start（会读 .env 注入 LLM key；restart_feishu.sh 只认环境变量，单独跑报 LLM_API_KEY 未配置）。5) 验证：心跳文件 state=connected + 主区心跳不受影响 + ps 确认进程路径含镜像目录。"
evidence: 镜像桥 PID 2332 state=connected 心跳 15s；主区桥 PID 77106 connected 不受影响；镜像 .feishu.env 为 cli_a9278…（独立 app）；token 预检 code=0/7199s；ps eww 确认 PYTHONPATH=镜像/src + LFL_DATA_DIR=镜像/data。
tags: [飞书桥, 镜像隔离, MIRROR协议, pgrep精确匹配, PYTHONPATH, 凭证管理]
source: {}
status: active
created_at: "2026-08-22T10:45:59.905481+08:00"
updated_at: "2026-08-22T10:45:59.905481+08:00"
---