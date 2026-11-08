---
title: deepin wheel 布局 LFL 三服务重启：权威入口结构性 fail-closed（restart_mirror.sh dual-root identity），保形 stop/start 是唯一正路且知识随启动重扫生效
scenario: "用户授权重启 deepin 宿主上的 LFL web/飞书/learning 使 eb51e82 代次与知识资产生效。此前两轮结论：service_control restart 因控制面 sanity check（parents[3] 须含 src/llm_loop）在 wheel 布局失败；wheel 0.6.39 venv 的 src 与 eb51e82 逐文件一致，仅缺 _bundled。"
root_cause: ""
solution: 不走 managed restart（结构性不可行，不伪造 identity 输入），走 SSH 保形重启：逐服务 TERM→验证→下一个；web 用官方 venv `lfl --workspace /home/operator/lfl-workspace web`，feishu/learning 用 workspace checkout .venv `python -m llm_loop.runtime.launch`；setsid nohup 拉起，验证锚点=web /health knowledge records(19/2)+webui sha 不变、feishu 心跳 connected+新 pid、learning manifest healthy+新 pid。
evidence: "evidence://v1/bcd869bb92c9b3e8ac99eb0d8890ef08ff7d60dae1e6e86ef1267998dd692e03 (wheel src ≡ eb51e82 diff 为空)；/tmp/rm_eb51e82.sh L215/L222（git show eb51e82:scripts/restart_mirror.sh）；web 重启回执（newpid、HEALTH-OK、records:19/2）；feishu 心跳 connected pid 641271；learning manifest healthy pid 642363"
tags: [service_control, deepin, wheel布局, restart, 保形重启, dual-root-identity, fail-closed, ssh]
source:
  host: operator-PC(deepin) via ssh operator@[private LAN address redacted]
  date: 2026-11-07
  time: "01:26-01:35"
  session_context: Mac 会话执行，eb51e82=gen6 已发布、知识 9exp+2method 已刷入状态目录
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-07T01:33:45.248806+08:00"
updated_at: "2026-11-07T01:33:45.248806+08:00"
---

deepin 宿主（wheel 安装布局：runtime_root=/home/operator/.local/share/lfl 为安装器状态目录，服务代码在 releases/LFL-0.6.39/venv 与 /home/operator/lfl-workspace/llm-first-loop）上重启 LFL web/feishu/learning 的已验证路径：(1) 先取三进程精确形态（ps args+cwd+env、/proc/pid/environ）；(2) 逐个 TERM→端口/心跳/manifest 验证→再动下一个，web 先行；(3) web 用官方 venv `lfl --workspace /home/operator/lfl-workspace web`，feishu/learning 用 workspace checkout `.venv/bin/python -m llm_loop.runtime.launch <svc>`，setsid nohup 脱离 ssh 会话；(4) 验证锚点：web=/health 的 knowledge records（重启触发全量重扫，9→19 即知识生效证据）+ webui source sha 不变；feishu=feishu_heartbeat.json state=connected+新 pid；learning=runtime_manifest.learning.json pid+status healthy。两个坑：launcher 进程会二次 fork（pgrep 首捕 pid ≠ 最终 manifest pid，以 manifest/proc 终态为准）；ssh 单命令含轮询会撞 execute_command 60s 上限——拉起与验证拆两次调用。结构性事实：service_control 权威重启在该布局永不可行——restart_mirror.sh `_validate_restart_roots` 的 dual-root identity 检查（L215 要求 $RUNTIME_ROOT/.venv、L222 要求双根同仓 git-common-dir、身份类不可 override 穿透），而安装器状态目录不是 git worktree；即便按 00:32 报告方案 1 用 PYTHONPATH=checkout/src 过了控制面 sanity check，restart 仍会在这里 fail-closed。不得伪造 .venv/仓库结构绕过。