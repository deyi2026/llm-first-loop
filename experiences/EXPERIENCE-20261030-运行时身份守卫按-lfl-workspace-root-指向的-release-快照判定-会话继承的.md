---
title: 运行时身份守卫按 LFL_WORKSPACE_ROOT 指向的 release 快照判定；会话继承的旧 release 变量会让新代码启动被拒
scenario: 在部署根用新代码启动服务（python -m llm_loop.wecom）时，身份守卫报 FATAL_RUNTIME_IDENTITY_MISMATCH 并 refuse to start：期望 src 指向 .releases/<旧 sha>/src，而实际加载的是部署根 src。
root_cause: ""
solution: |
  身份期望由 LFL_WORKSPACE_ROOT / LFL_DEFAULT_WORKSPACE_ROOT 决定（默认回落为 workspace/src）。会话环境常继承着上一次发布钉住的 release 路径 → 启动前必须 unset 这两个变量并显式设 LFL_DEFAULT_WORKSPACE_ROOT=<部署根>、PYTHONPATH=<部署根>/src、cwd=部署根，与 scripts/restart_system.sh 的语义一致（该脚本的 PYTHONPATH 把部署根 src 放在首位）。
  当前性验证：先跑 `echo "LFL_WORKSPACE_ROOT=${LFL_WORKSPACE_ROOT:-<空>}"; grep -n 'PYTHONPATH=' scripts/restart_system.sh` 确认变量是否仍被继承、restart 脚本的 PYTHONPATH 语义是否仍是「部署根 src 优先」；再复现：env -u LFL_WORKSPACE_ROOT -u LFL_DEFAULT_WORKSPACE_ROOT LFL_DEFAULT_WORKSPACE_ROOT=<部署根> PYTHONPATH=<root>/src python -m llm_loop.wecom，应只输出业务配置类报错而不出现 FATAL_RUNTIME_IDENTITY_MISMATCH。
evidence: "本轮实测：env -u LFL_WORKSPACE_ROOT -u LFL_DEFAULT_WORKSPACE_ROOT LFL_DEFAULT_WORKSPACE_ROOT=<部署根> PYTHONPATH=<root>/src .venv/bin/python -m llm_loop.wecom → 身份守卫不再报警，唯一输出变为预期的「❌ 企微桥配置缺失: WECHAT_BOT_ID、WECHAT_BOT_SECRET 未设置」；未 unset 时则 FATAL_RUNTIME_IDENTITY_MISMATCH + refusing to start。"
tags: [runtime, 身份守卫, release, 部署, 启动环境]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T01:46:18.052185+08:00"
updated_at: "2026-10-30T01:46:18.052185+08:00"
---