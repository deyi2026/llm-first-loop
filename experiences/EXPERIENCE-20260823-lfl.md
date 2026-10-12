---
title: LFL 多实例（主区/镜像区）环境隔离排障：进程启动环境决定路径解析的同类问题全景
scenario: "用户报告\"本地模型会去查主区路径导致任务失败\"。排查发现根因是：本地模型会话跑在主区 web（8902）进程里，该进程 cwd/workspace_root=主区，工具默认路径（execute_command 的 workspace_base()=os.getcwd()、dsh_task/dsh_session_read 的默认 workspace）全部落主区。用 grill 拷问模式系统性排查同类问题后，又发现 4 项：①镜像区进程 DSH_HOME 未重定向（落全局 ~/.dsh，镜像区无 data/dsh-home，dsh_session_read 按镜像 workspace_key 找不到目录）②镜像区 web/feishu 进程环境携带主区 DSH_SESSION_JSONL/DSH_SESSION_ID（启动环境残留）③主区/镜像区 git HEAD 分叉 + providers.json/.env 不同步 ④镜像区 interop 缺 dsh_to_lfl（LFL inbox）目录。"
root_cause: "多实例 LFL 部署中\"进程启动环境（cwd/工作区根/DSH 环境变量/环境残留）决定工具与数据路径解析\"，主区与镜像区进程环境未隔离：镜像服务从主区 DSH 会话环境启动继承主区变量，且 restart_mirror.sh 未重定向 DSH_HOME，导致路径跨区错位。"
solution: "1) 修复 restart_mirror.sh：新增 _prep_dsh_env()——export DSH_HOME=$MIRROR_DIR/data/dsh-home + mkdir -p + unset DSH_SESSION_JSONL/DSH_SESSION_ID/DSH_SHELL/DSH_WEB_URL，并在 _start_web/_start_feishu 启动前调用（source .env 之前先清理/设置 DSH 环境，避免主区残留污染镜像进程）。2) 建缺失目录：data/dsh-home、data/interop/dsh_to_lfl。3) 用 restart_mirror.sh web/feishu 重启（按端口杀 8903，绝不 pkill -f \"llm_loop.web\" 防误杀主区 8902）。4) 验证：新进程 ps eww 应只有 DSH_HOME=镜像区/data/dsh-home、无 DSH_SESSION_JSONL 残留、PWD=镜像区、8903 health ok 且 8902 主区不受影响。5) P2 代码/配置同步（git HEAD 分叉、providers.json history_budget_chars 400K vs 1M、TOOL_SUMMARY_THRESHOLD 15000 vs 6000）需人工决策同步策略，AI 不应擅自改主区生产。"
evidence: "ps eww 实测：主区 web(842) DSH_HOME=主区/data/dsh-home、cwd=主区；镜像区 web(93723) 原 DSH_HOME=~/.dsh、携带 DSH_SESSION_JSONL 指向主区 session；修复后新 web(34264)/feishu(32680) 仅 DSH_HOME=镜像区/data/dsh-home。dsh_session_read.py:124-127 用 DSH_HOME 定 sessions 根；run_context.py:36-43 workspace_base()=current_workspace_root 或 os.getcwd()。镜像区原无 data/dsh-home 与 data/interop/dsh_to_lfl。"
tags: [多实例隔离, DSH_HOME, workspace_base, 环境残留, restart_mirror, 路径解析, 排障]
source: {}
status: active
created_at: "2026-08-23T00:52:19.319009+08:00"
updated_at: "2026-08-23T00:52:19.319009+08:00"
---