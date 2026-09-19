---
method_id: spa-shell-static-bundle-escalation-4a987f7ccaac
name: spa-shell-static-bundle-escalation
description: 针对『分析这个网站/项目』类任务：当 fetch 成功但返回 JS 壳页（title/OG 完整、正文极简、extract 标注 embedded_json）时，不要重复抓同一 URL，也不要直接跳浏览器渲染。正确次序：取原始 HTML 定位主 JS bundle -> 顺带取 robots/sitemap 得路由图 -> 对 bundle 做中文文案与绝对 URL/API 端点提取。SPA 官网/文档站的文案、外部仓库、后端 API、第三方依赖几乎全部内嵌在 bundle 里，足以支撑项目分析。只有 bundle 证明内容是运行时从 API 拉取、或任务需要交互/截图时才升级渲染——且升级前先读渲染工具的白名单/helper 约束，而不是用失败去发现约束。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:0:a03c220d4473c1e718e1
evidence_refs: learning:learn:d2808453d5bf
created_at: 2026-09-18T01:53:22.006121+00:00
updated_at: 2026-09-18T01:53:22.006121+00:00
---
## Trigger
web fetch 成功但返回壳页：title/meta 完整、body 近空、extract 标注 embedded_json 或提示内容由 JS 渲染；且任务目标是分析站点/项目内容，而非验证交互

## Discriminator
第一次抓取的回执本身就是判别事实：status=success + title + 近空 body + extract=embedded_json，说明抓取器只能拿到壳、正文由 JS bundle 生产；同一工具重复抓同一 URL 不会产生新事实，下一步应指向『找到内容的生产者』（原始 HTML 里的主 script src），而非重试抓取或盲目升级渲染

## Short path
- 依据首次回执确认壳页，不再重复抓取同一 URL；未知量：正文由哪个 artifact 生产
- curl 原始 HTML，定位主 bundle 的 script src、root 挂载点，并从 modulepreload 列表得到技术栈初步证据；未知量：内容来源与前端栈
- 并行取 robots.txt + sitemap.xml 得到路由图与抓取约束（Disallow 路径），同时下载主 bundle；未知量：有哪些子页、允许抓什么
- 对 bundle 做 CJK 文案 + 绝对 URL/API 端点正则提取，得到页面文案、外部仓库、后端 API 域、第三方依赖（认证/字体/CDN）
- 用 bundle 中发现的外链到权威来源（如 GitHub API）交叉核实站点关键可量化主张；未知量：宣称是否可信
- 仅当 bundle 证明正文是运行时 API 拉取、或需要交互/截图验证时才升级渲染；写浏览器代码前先读该工具 schema 的白名单与 helper 约束，域名不在白名单则立即转纯静态路径

## Stop conditions
- 文案+路由图+外链+技术栈已覆盖用户分析问题所需维度（定位/工程事实/可核验主张/风险）
- bundle 显示正文由后端 API 运行时加载（bundle 内几乎无文案）-> 停止 bundle 文案提取，转而针对 API 响应或（若被允许）渲染器
- 关键主张已获外部权威来源交叉核验，继续读 bundle 长文不再为结论增加信息

## Verification
- bundle 提取出的文案与 HTML 的 meta/OG/JSON-LD 相互印证（title、description、组织信息一致）
- 站点可量化主张（stars、release 产物、代码量）用 bundle 中发现的外链做外部核验，不单信站方文案
- 实际抓取的路径遵守 robots.txt 的 Disallow 约束

## Counterexamples
- 服务端渲染/静态页面 body 已含完整内容 -> 直接分析并停止，无需读 bundle
- 正文由前端运行时 fetch 后端 API 动态拼装（bundle 内几乎无文案）-> bundle 文案提取无效，需抓 API 响应或用允许的渲染器
- 任务要求验证登录态、交互流程或视觉布局 -> 静态分析不能替代渲染
- bundle 重度代码分割、文案分散在各路由懒加载 chunk -> 需按路由定位并下载对应 chunk，仅分析主 bundle 会漏内容
- 渲染工具白名单本就包含目标域名且内容强动态 -> 直接渲染可能比逆向分析大体积 bundle 更省
