---
title: web_search 后端降级时改用 web_fetch 直取一手页面
scenario: 需要引用外部最新事实写分析文时，web_search 返回大量首页/词典页/营销页等无关命中（本次 3 次多 query 检索基本无有效一手文档命中）
root_cause: ""
solution: 放弃继续调 web_search，直接 web_fetch 已知一手 URL（厂商官方 docs / 工程博客首页）；本次用该路径取得 6 份完整一手信源（Anthropic 多 agent 工程博客、Claude Code subagents 与 agent-teams 文档、Cursor background agents、GitHub Copilot in the cloud、Devin 文档），抓到版本门槛、限制清单与量化数字
evidence: "evidence://v1/927a3fcfa397e0c442aab34f5a7ee458848bb10a13975891b08cf40a9fdc0e5a; evidence://v1/bbaf59a71c17b19283d230c4d59c2ea075b07da4e1e0ba57327e86c7e87611cf; evidence://v1/0b9f4b10524cf5e71667ddba29d3303abc6441307ba7d5b22cc1c64dd279c8da; evidence://v1/eec5a945c99ac9e30bbd6e19bc99741ec2359aee356b066314ef95370030f8c4"
tags: [web-research, evidence-provenance, analysis-doc]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-14T13:36:11.550123+08:00"
updated_at: "2026-11-14T13:36:11.550123+08:00"
---
