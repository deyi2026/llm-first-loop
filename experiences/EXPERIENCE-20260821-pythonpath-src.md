---
title: 镜像工作区验证代码改动必须用 PYTHONPATH 指向镜像 src（双真相源坑）
scenario: "在 llm-first-loop-mirror 工作区用 .venv/bin/python 直接跑脚本/验证时，editable 安装的 llm_loop 包实际指向主区 src——验证脚本加载的是主区旧代码，导致\"改了镜像 store.py 但 search() 签名还是旧的\"（TypeError: unexpected keyword argument 'session_id'）。测试通过是因为 conftest 前置了镜像 src 到 sys.path。"
root_cause: 共享 venv 的 editable 安装（.venv 的 llm_loop.egg-link/pth）指向主区 src，镜像工作区的 src 不在 sys.path 默认搜索路径内；直接运行脚本时 Python 按 sys.path 找包，加载了主区代码而非镜像代码。
solution: "镜像区验证代码改动一律加 PYTHONPATH=/Users/yyj/Project/llm-first-loop-mirror/src 前缀：PYTHONPATH=.../src .venv/bin/python -c \"...\"; 或跑 pytest 时同样加 PYTHONPATH（或依赖 conftest 的 sys.path 前置）。判断是否加载了正确代码：检查目标函数签名（inspect.signature）确认新参数已生效，不要凭 import 成功就认为代码是最新的。"
evidence: 2026-08-20 P0-2 记忆分级验证：MemoryStore.search() 报 unexpected keyword argument 'session_id'（加载了主区旧代码）；加 PYTHONPATH=镜像 src 后签名确认 session_id 已生效、过滤验证通过。记忆库条目 MEM-20260820-24487c58（双真相源风险）佐证。
tags: [mirror-workspace, python-path, editable-install, verification]
source: {}
status: active
created_at: "2026-08-21T00:25:01.440019+08:00"
updated_at: "2026-08-21T00:25:01.440019+08:00"
---