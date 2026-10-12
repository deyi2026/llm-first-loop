---
title: 沙箱 execute_command 中 HOME 被重定向，Path.home() 不可靠
scenario: 在 execute_command 里写的工具脚本需要访问用户主目录资源（如 ~/.lmstudio/models）
root_cause: ""
solution: 任何用户目录路径都显式化：DEFAULT_CONFIG paths.models_dir 写死绝对路径 + LMSTUDIO_MODELS_DIR env 覆盖 + Path.home() 兜底，取第一个存在的候选
evidence: 命令行复现：python3 中 Path.home() 返回 /var/folders/yx/.../mcp-console/.../home；修复后 lfrt models 列出 6 个模型
tags: [sandbox, execute_command, HOME, Path.home, macos, python]
source: {}
status: active
created_at: "2026-09-11T09:00:23.251848+08:00"
updated_at: "2026-09-11T09:00:23.251848+08:00"
---

execute_command 会把 HOME 指向 /var/folders/.../mcp-console/.../home（每命令独立沙箱），Path.home() 与 os.path.expanduser("~") 都解析错。症状：扫描用户目录的代码静默返回空（不报错）。修复：显式配置路径 + 候选链（env var → config → 真实绝对路径），并自检首个存在的候选。launchctl/domain/ps 不受影响（不读 HOME）。调试技巧：无扩展名脚本用 SourceFileLoader("m","./lfrt").load_module() 直接加载调函数。