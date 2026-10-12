---
title: 用 code.claude.com/docs/llms.txt 批量抓取 Claude Code 官方文档原文
scenario: 需要 Claude Code / sub-agents / plugins 等特性的权威定义，但 web_search 搜不到一手页面，直接猜 docs URL 路径返回 404。
root_cause: ""
solution: "curl https://code.claude.com/docs/llms.txt 拿到全部文档页的 .md 直链清单（含每个页面标题与摘要）；用 grep -oE 过滤出目标章节（如 plugins/mods/[a-z-]+\.md）后循环 curl 到本地目录，再用 read_file / grep 精读。同一目录下的 CHANGELOG.md（raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md）可用 python 按 \"## <version>\" 切段 + 关键词过滤，得到某特性跨版本的完整变更时间线，比读二手转述可靠。"
evidence: 2026-10-09 会话：llms.txt 返回 200/109KB，成功批量取得 10 页 mods 文档（260KB）；CHANGELOG 切段得到 69 条 mods 相关条目横跨 19 个版本，纠正了二手文章关于 Mods 引入版本的说法。
tags: [claude-code, docs, llms.txt, changelog, research]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-09T01:39:35.971834+08:00"
updated_at: "2026-10-09T01:39:35.971834+08:00"
---