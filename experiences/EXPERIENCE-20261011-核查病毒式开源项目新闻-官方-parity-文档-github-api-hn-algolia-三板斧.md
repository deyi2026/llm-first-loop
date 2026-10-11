---
title: 核查病毒式开源项目新闻：官方 parity 文档 + GitHub API + HN Algolia 三板斧
scenario: 核实一篇关于 GitHub 开源项目（AI 重写商业软件）的中文科技媒体报道的真伪与准确度
root_cause: ""
solution: "用官方仓库的一手数据替代新闻转述链：GitHub org/repo API 核时间线与人物、raw README/parity 文档核完成度自评、contributors.json 核\"AI 写代码\"主张、HN Algolia API 核社区讨论；注意区分完成度的不同口径（功能广度 vs 真正可用）与快照时效。当前性验证：web_fetch https://api.github.com/repos/storytold/photocraft 确认仓库存在未 archived，再取 raw main/docs/parity-estimate.md 确认关键字 \"menu/command breadth\" 仍在，数字变化则更新。"
evidence: "evidence://v1/2b93298fd587b090eea94c7385af82ed6ecb972bac4998653fc6a51ad8b6e01b (photocraft contributors.json，AI 模型共同署名)；evidence://v1/9c5cd170c5d9cc53c33182ed519532593dadeeaee1c2f97f53f6c4a5637dce78 (photocraft parity-estimate.md)；evidence://v1/e27cc385e6d97efccd1d14553bf19016fda07bf79ae670ab028458dde24fd09d (HN Algolia)；GitHub users/echelon 回执（Brandon Thomas 档案）"
tags: [fact-checking, github-api, hn-algolia, open-source, web-verification]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-11T02:24:30.492144+08:00"
updated_at: "2026-10-11T02:24:30.492144+08:00"
---

2026-10-11 核实中文科技媒体（头条转载）关于 ArtCraft 团队用 AI+Rust 重写 Adobe 全家桶的报道。有效路径：(1) GitHub API（/orgs/X/repos、/repos/X/Y、/releases、/users/）拿仓库真实性、stars、发布时间线、开发者档案——主力贡献者 echelon 的 profile 直接确认姓名/城市/公司/bio；(2) raw.githubusercontent.com/<org>/<repo>/main/README.md 与 docs/*.md（尤其 target-app-parity.md / parity-estimate.md / contributors.json）拿官方自评完成度、AI 模型共同署名、代码行数；(3) hn.algolia.com/api/v1/search?query=... 与 /items/<id> 拿 HN 讨论与社区反馈（Reddit 有反爬，改用媒体转述+HN）。注意点：完成度数字有两个口径（feature breadth vs ready for real work），媒体常混用且引用旧快照；仓库改名有 301 重定向（printcraft→pdfcraft）可用 API 直接验证。反例：bing 中文站对英文小众查询（人名+公司）几乎无用，Futurism 原文多次尝试未获取，只能标注"媒体转述未独立核实"。当前性验证：web_fetch https://api.github.com/repos/storytold/photocraft 应返回 watchers>0 且未 archived；再取 raw main/docs/parity-estimate.md 应含 "menu/command breadth" 字样，若 404 或数字大幅变化则按新证据更新结论。