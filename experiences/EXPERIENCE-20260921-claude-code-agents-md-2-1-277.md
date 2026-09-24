---
title: Claude Code 升级前必查：AGENTS.md 自动加载是 2.1.277 新增且默认开启
scenario: 评估升级 @anthropic-ai/claude-code（native 安装）到 2.1.27x 的风险，尤其工作区已存在为其他 agent 框架写的 AGENTS.md 时
root_cause: ""
solution: 不要只读 changelog 或搜索文档，直接取平台二进制做 strings 取证：1) `npm view @anthropic-ai/claude-code dist-tags` 看 latest/stable；2) `npm pack @anthropic-ai/claude-code-darwin-arm64@<ver>` 拿到真二进制（主包只是 196K 启动器，真代码在平台可选依赖里，约 200M）；3) 对已装版本与新版本分别 `strings -a -n 6 <bin> | grep -c <feature>` 比对，功能在旧版计数为 0 即说明是新增行为；4) 用 python 读二进制字节、把非可打印字符转换行后按关键词过滤，可还原被内联的插件模块（如 instructionFiles 的四个取值与默认值）。关键结论：AGENTS.md 支持自 2.1.277 起默认 `claude-md-or-agents-md`，即项目无 CLAUDE.md 时把 AGENTS.md 当项目指令注入；若 AGENTS.md 属于别的 agent 系统（含自启动脚本/人格指令），升级会引入 prompt 注入面，需在 /config 的 Project instructions 改回 claude-md。另注意 2.1.275 有让 ANTHROPIC_BASE_URL 网关每个请求 400(Input tag 'advisor_20260301') 的回归，2.1.277 修复。
evidence: "2.1.204 二进制 grep -c instructionFiles=0 / claude-md-or-agents-md=0，AGENTS.md 仅 2 处且位于 /init 提示词文本；2.1.278 二进制 instructionFiles=14、AGENTS.md=14，插件模块含 instructionFiles 选项全文与默认值 claude-md-or-agents-md；官方 CHANGELOG 行 \"2.1.277: Added AGENTS.md support: in a project with no CLAUDE.md, Claude Code reads AGENTS.md instead\"；本机存在 ~/AGENTS.md、~/workspace/AGENTS.md、~/workspace/dlkimi/AGENTS.md 且无任何 CLAUDE.md"
tags: [claude-code, upgrade-risk, agents-md, binary-forensics, prompt-injection]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-21T04:03:50.229430+08:00"
updated_at: "2026-09-21T04:03:50.229430+08:00"
---