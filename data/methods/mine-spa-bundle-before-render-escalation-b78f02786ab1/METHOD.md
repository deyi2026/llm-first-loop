---
method_id: mine-spa-bundle-before-render-escalation-b78f02786ab1
name: mine-spa-bundle-before-render-escalation
description: 轻量抓取只返回 JS 渲染壳页（extract=embedded_json、仅 title/meta）时，不要重复抓取，也不要立即升级浏览器渲染：先取原始 HTML，沿显式 <script src> 引用边下载主 bundle，用脚本机械提取 CJK 文案与全部 URL/端点。静态打包 SPA 的正文常整体内嵌在 bundle 中，比渲染更便宜且信息更全（含外链、API 端点、内嵌文档），同批可取 robots+sitemap 获路由图。仅当 bundle 被证明只含 UI 标签、内容来自运行时 API 时才升级渲染。另：调用重工具（浏览器/E2E）前先读其 Schema 与白名单约束，避免裸调用触发门控失败。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:0:a03c220d4473c1e718e1
evidence_refs: learning:learn:d2808453d5bf
created_at: 2026-09-18T01:53:11.785572+00:00
updated_at: 2026-09-18T01:53:11.785572+00:00
---
## Trigger
轻量 HTTP 抓取返回站点壳页：正文缺失或极短、extract 标记为 embedded_json 或仅 title+meta，表明内容由前端 JS 渲染，而用户需要页面实际内容或站点整体分析。

## Discriminator
首次抓取结果本身已含判别事实：extract 仅 embedded_json、正文为空、无 SSR 痕迹，且助手当场已判断'JS 驱动的站点'。这一事实足以把候选动作（重复抓取/浏览器渲染/宽枚举）缩小为一条因果边：取原始 HTML，定位生产内容的主 bundle 引用。无需任何后续才知的信息。

## Short path
- 轻量抓取目标 URL，判定正文是否已在静态 HTML 中（本例：仅 embedded_json 壳）→ 不重复抓取同一 URL
- 壳页则 curl 原始 HTML，解决未知量'哪个脚本生产内容'：读取 <script type=module src>、#root 挂载点、modulepreload 技术栈线索
- 下载主 bundle，用脚本一次性提取 CJK 字符串与全部 URL/API 端点（聚合用代码做，不靠脑内拼接），解决未知量'站点实际内容与外链'
- 同批取 robots+sitemap，获得路由结构与禁抓边界（分析类任务需要站点全貌）
- 分块阅读提取结果；对外部关键主张（仓库、下载、API 端点）用权威来源二次核实后即可作答，全程无重复抓取、无失败重试

## Stop conditions
- bundle 提取的文案/外链与 meta、权威来源互证一致后，足以支撑用户所需分析即停止
- 发现 bundle 仅含 UI 标签、真实内容来自运行时后端 API → 停止 bundle 挖掘，改走浏览器渲染或网络响应层
- 静态 HTML 已含完整目标正文 → 直接分析，不碰 bundle

## Verification
- 提取文案中的标题/描述与原始 HTML 的 meta description、og:title 互证一致
- bundle 中发现的外部事实（GitHub 仓库、下载链接、API 端点）在独立权威来源（如 GitHub API）再次核实
- 确认未请求 robots 禁止路径；确无对同一 URL 的短时重复抓取

## Counterexamples
- SSR/静态页已直接包含完整目标正文 → 直接分析并停止，挖 bundle 是浪费
- SPA 内容来自运行时 XHR/API（bundle 只有代码与少量 UI 文案，如电商商品列表）→ bundle 挖掘拿不到目标内容，应渲染页面或读网络响应
- 目标是交互行为或视觉呈现（canvas/WebGL 动画、登录态后内容）而非文本 → 字符串提取无效，且重工具白名单允许时应先读 Schema 再直接渲染，反而更短
- bundle 体积巨大而目标内容极小且在单一 API 后面 → 成本收益反转，应先定位该 API
