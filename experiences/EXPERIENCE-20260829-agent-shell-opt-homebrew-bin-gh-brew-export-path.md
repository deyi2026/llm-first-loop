---
title: agent shell 无 /opt/homebrew/bin：gh/brew 系工具需显式 export PATH 后才可用
scenario: LFL agent 通过 execute_command 使用用户终端已安装的 Homebrew 工具（gh/brew 系 CLI）
root_cause: "LFL agent shell 为 /bin/sh，非交互模式不加载 .zshrc，PATH 缺 /opt/homebrew/bin；用户 zsh 终端有完整 PATH 所以能跑，造成\"用户终端可用但 agent 报 command not found\"的分裂。"
solution: "命令前置 export PATH=\"/opt/homebrew/bin:$PATH\"；涉及 DSH 时同时加 /Users/yyj/.hermes/node/bin"
evidence: "evidence://v1/79d7ce0ff316315d8443c57d911eb6f8d36be798c7b173c72c85ef6879641f7c；evidence://v1/c8ef9821faa075c0b48fec51c9ef15c8846d349cdeda9b3b90d6f3c478ba3a38"
tags: [gh, PATH, Homebrew, execute_command, agent-shell, issue]
source: {}
status: active
created_at: "2026-08-29T11:07:19.840829+08:00"
updated_at: "2026-08-29T11:07:19.840829+08:00"
---

LFL agent 的 execute_command 用 /bin/sh（受限 PATH，无 /opt/homebrew/bin）——gh、node、brew 系工具直接调用会 command not found。修正：命令前缀 export PATH="/opt/homebrew/bin:$PATH"（DSH node 场景为 export PATH="/Users/yyj/.hermes/node/bin:/opt/homebrew/bin:$PATH"）。用户终端能跑 ≠ agent shell 能跑（zsh 有 .zshrc 的 PATH 扩展，/bin/sh 没有）。gh 已装 2.98.0 且已登录（keyring，account deyi2026），gh issue create -R owner/repo --title ... --body-file 是可复用通道。