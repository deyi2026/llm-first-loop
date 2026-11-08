---
title: Agent 指令文件投毒（AGENTS.md/CLAUDE.md）的本机四步分诊法
scenario: "读到/听说\"网页静默投放 AGENTS.md 投毒 Coding Agent\"这类披露后，需要判断本机是否被污染，而不能只转述文章。"
root_cause: ""
solution: "用只读四步分诊，不必复刻攻击链：(1) 入口——检查 ~/Downloads、~/Desktop 及各项目根是否有来路不明的 AGENTS.md/CLAUDE.md，并对其内容做零宽 Unicode 扫描（U+200B/200C/200D/2060/FEFF/180E）；(2) 持久化——读 ~/.codex/config.toml 的 [mcp_servers.*] 与 ~/.claude/settings.json 的 env，核对每个 command/url 是否都是自己装的（官方 app bundle、自建服务）；(3) 恶意包——查 /tmp/ptools、npm 全局包与 ~/.npm/_cacache/index-v5 中是否出现 function-color/function-flag；(4) 网关劫持——对比 ANTHROPIC_BASE_URL 与各项目 .claude/settings.json。同时用 git log/status 确认仓库内同名文件是自家受控产物而非投放。注意：env 里的第三方 BASE_URL 常是用户主动配置，需用备份文件时间线+项目文档交叉验证后再下结论，不可凭\"命中就断定被投毒\"。判定为非投毒的依据要逐条列明，零宽命中必须给出上下文判断而非仅计数。"
evidence: "本次在 macOS 实机执行四步分诊：~/Downloads 与 ~/Desktop 无 AGENTS.md/CLAUDE.md；~/.codex/config.toml 的 mcp_servers 仅为 ChatGPT.app 自带 node_repl/computer-use 与用户自建 mcp.llmfirstloop.com；/tmp/ptools 不存在、npm 全局与 cacache index-v5 未见 function-color/function-flag；~/.claude/settings.json 的 ANTHROPIC_BASE_URL=https://ai.mxnook.com 经 settings.json.bak-20260920 与仓库 docs/injection-governance/r8 交叉验证为用户自配 relay（且 token 已于 20260921 轮换）。零宽扫描 55 个 md 仅 1 个命中 9 处 U+200B，逐条上下文均为 StackOverflow/Django 文档排版空格，非注入。"
tags: [security, prompt-injection, agent, triage, codex, claude-code]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-07T13:12:48.715496+08:00"
updated_at: "2026-11-07T13:12:48.715496+08:00"
---