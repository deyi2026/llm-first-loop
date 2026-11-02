---
title: "代码时效判断：对照基准要按部署形态推导，不能取 manifest/环境里的\"workspace_root\""
scenario: "要给\"我改的代码运行中进程真的在跑吗\"做机械判断。系统用 release 部署：服务从 <repo>/.releases/<sha>/src/llm_loop 加载，manifest 记录的 workspace_root 与 llm_loop_module 都指向该 release 目录，且 release 副本自带独立 .git。"
root_cause: "部署形态（release 副本 + 副本自带 .git + LFL_WORKSPACE_ROOT 指向副本）使\"环境变量/manifest 里的路径\"与\"可编辑源码树\"脱钩；基于该路径的 git HEAD 与 dirty 探测在同一副本内自洽，于是恒判 code_current=true。"
solution: "1) 先核事实：读 manifest 里 workspace_root / llm_loop_module 的真实取值、check `git -C <release> rev-parse --show-toplevel`、看 release 下是否有 .git。2) 结论：这两个\"看起来像源码树\"的字段在此形态下就是执行目录本身，拿它们做对照基准 = 恒等比对 → 永远报\"一致\"；git 探测也会停在副本自带的 .git 里。3) 正确基准：用路径结构反推——把加载路径里 `.releases/<sha>/` 之前的段当仓根，再取 <repo>/src/<pkg>；并用\"该目录是否含守卫模块文件\"做可用性闸（缺失→unknown，不判 stale）。4) 判据分层：只有\"本进程已 import 的模块\"内容变化才算 stale（未 import 的模块首次 import 会读到新码，记 changed_unloaded 而非 stale）；未知一律 None/unknown，禁止退化成\"一致\"。"
evidence: "architecture_status(process_versions) 实测：current_git_head=ce205a4da、workspace_dirty=false、web/feishu code_current=true、note=\"\"，而仓库当时已有新提交与改动；manifest 实测 workspace_root=<repo>/.releases/ce205a4.../、llm_loop_module=.../src/llm_loop/__init__.py；模拟 release 形态端到端：按 .releases 反推后 guard_code_drift()→stale=True 点名 core/command_scope_guard.py，service_control 视图同判 stale；tests/unit/test_guard_code_freshness.py 12 条 + test_proc_version.py 共 23 passed。提交 35c932627。"
tags: [代码时效, release部署, 对照基准, git探测, 守卫模块]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-01T13:15:22.203785+08:00"
updated_at: "2026-11-01T13:15:22.203785+08:00"
---