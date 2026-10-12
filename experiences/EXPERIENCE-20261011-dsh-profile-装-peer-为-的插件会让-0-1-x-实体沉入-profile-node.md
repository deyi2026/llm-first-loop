---
title: "dsh profile: 装 peer 为 \"*\" 的插件会让 0.1.x 实体沉入 profile node_modules 并遮蔽 bundle 内的 0.2.x"
scenario: "DSH 0.2.0-rc.2 升级后 `dsh web` 启动失败，报 \"1 required plugin did not activate\"，agent-loop 等 11 个插件全部 waiting on 服务 `llm`，日志里 plugin row \"llm\" 被判 incompatible。排查发现 profile 的 node_modules/@deepseek-ai 下有实体 dsh-llm@0.1.0-rc.8（装 ds-bot 时引入），而 bundle 内是 0.2.0-rc.2。"
root_cause: "profile 的 pnpm-workspace.yaml 用 nodeLinker: hoisted。ds-bot@0.1.2 声明 peerDep `@deepseek-ai/dsh-llm: \"*\"`，pnpm 为它解析并实体安装了 0.1.0-rc.8 到 profile 的 node_modules。hoisted 布局下 profile/node_modules 优先于 CLI 内嵌 node_modules，0.1.x 的实体遮蔽了 bundle 内的 0.2.0-rc.2，dsh-base 的 llm 插件行因此按 0.1.x 做 peer 兼容性检查而失败。"
solution: "不要用 `dsh plugin allow-version` 豁免，要做版本对齐：把 profile 本地那份升到与运行时一致的版本，让 peer `*` 解析到正确版本——`dsh plugin --profile web add @deepseek-ai/dsh-llm@0.2.0-rc.2`（精确版本，不带 caret，避免又被解析回 0.1.x）。验证点：profile-local dsh-llm 版本 == CLI 版本；启动后不再出现 \"startup failed\" 且无 \"Plugins waiting for services\"。"
evidence: "启动日志 `Plugin @deepseek-ai/dsh-llm@0.1.0-rc.8 is incompatible with dsh 0.2.0-rc.2`；profile node_modules 中 dsh-llm=0.1.0-rc.8（mtime Oct 11 19:28，装 ds-bot 的同一次会话），而同目录 cosmokit/schemastery 仍是 8 月 21 日；bundle 内 dsh-llm=0.2.0-rc.2；ds-bot package.json peerDependencies 含 '@deepseek-ai/dsh-llm': '*'；pnpm-lock 记录 ds-bot@0.1.2(@deepseek-ai/dsh-llm@0.1.0-rc.8)。对齐后 dsh web 起在 127.0.0.1:3080，HTTP 200、34914 字节应用页。"
tags: [dsh, peerDependencies, pnpm, nodeLinker-hoisted, version-shadowing, startup-failure, deepseek-harness]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-11T19:34:06.963850+08:00"
updated_at: "2026-10-11T19:34:06.963850+08:00"
---