---
title: 核开源项目 star/版本/功能描述：GitHub API 403 时用 releases.atom + npm registry + ungh 镜像分层取证
scenario: "核验二手文章（今日头条/公众号）里\"某开源项目 star 数 N、某版本某日发布、某功能存在\"这类事实时，GitHub 官方 API（api.github.com）经本机代理常返 403，而 HTML 抓取被 trafilatura 抽取会丢掉 star 计数等结构性数字。"
root_cause: ""
solution: "按证据强度分层取证并标注来源等级：①raw.githubusercontent.com/<owner>/<repo>/main/README.md 与 registry.npmjs.org/<pkg> 的 readme 字段 → 核功能描述、安装方式、平台矩阵、破坏性变更；②github.com/<owner>/<repo>/releases.atom → 核最新发布 tag 与时间戳（条目含 tag:github.com,2008 与 <updated>）；③registry.npmjs.org/<pkg> 的 dist-tags.latest → 核当前发布版本；④star/forks 用第三方 GitHub API 镜像 ungh.cc/repos/<owner>/<repo>（JSON 直出 stars/watchers/forks），并明确标注它是镜像而非官方 API；⑤官方 api.github.com 403 时如实写\"官方 API 直连未核实\"，不换 UA 反复重试、不手写 curl 绕过 web_fetch 安全边界。"
evidence: "本次实际执行链：web_fetch api.github.com → 403；web_fetch raw.githubusercontent.com/README.md → 成功；web_fetch releases.atom → 拿到 v1.2.0 / 2026-11-05T02:43:58Z 与破坏性变更条目；web_fetch registry.npmjs.org/agent-desktop → dist-tags.latest=1.2.0；web_fetch ungh.cc/repos/vercel-labs/agent-desktop → stars=20934, forks=1551, pushedAt=2026-11-10。"
tags: [web_fetch, github, 事实核验, 开源项目, 降级取证]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-11T11:15:18.116555+08:00"
updated_at: "2026-11-11T11:15:18.116555+08:00"
supersedes: [EXPERIENCE-20261011-核查病毒式开源项目新闻-官方-parity-文档-github-api-hn-algolia-三板斧]
---