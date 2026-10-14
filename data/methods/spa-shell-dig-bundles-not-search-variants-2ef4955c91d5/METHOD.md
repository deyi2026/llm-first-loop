---
method_id: spa-shell-dig-bundles-not-search-variants-2ef4955c91d5
name: spa-shell-dig-bundles-not-search-variants
description: 当目标官网抓取只返回数行 hero 文案（SPA shell）且搜索词被同名实体污染或站点未被收录时，不要继续换词重搜、猜子页 URL 或重复抓首页。改为抓原始 HTML，沿 script/bundle 引用找到内嵌数据模块与真实路由，再沿 bundle/导航链接抓发布文章与公司页；第三方讨论线只做一次精确词搜索，零结果本身即为结论。本集省掉重复污染搜索、404 猜路由与重复抓首页约 4 次无效调用。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b08a5a88-4c62-47f9-84ed-c3cb191c061d:4:bf5d3570e3fe26d3d043
evidence_refs: learning:learn:94b1fa966201
created_at: 2026-10-14T19:16:25.064218+08:00
updated_at: 2026-10-14T19:16:25.064218+08:00
---
## Trigger
官网可直接访问但正文抓取只返回极简 hero 文案（extract 工具拿到 SPA shell），且搜索引擎结果被同名实体污染或对新站零收录，需要获取站点深层内容（榜单数据/规则/子页）时

## Discriminator
当时已知两个事实：抓取回执 [extract] trafilatura 仅得 4 行 hero 文案且含 'Click a task…' 交互提示，内容为客户端渲染；同时首轮搜索 9/9 被同名游戏霸屏，该词的变体搜索已知必败。二者共同指向唯一可信下一跳：读原始 HTML 的 script/bundle 引用。

## Short path
- 首搜被污染后记录该事实，不再对同词做变体搜索；直接抓官网原始 HTML（curl/无提取模式）。未知量：内容由哪个脚本生产、站点真实路由是什么
- 解析 HTML 中 script/modulepreload 与路由脚本，下载入口 bundle 并读其 import 图与头部。未知量：数据模块在哪
- 在数据 bundle 头部定位内嵌 JSON（generated_at/models/tasks 字面量）。未知量：榜单、任务、成本口径真值
- 沿 bundle 或导航中出现的 /blog/ 与公司官网链接抓发布文章和背景页。未知量：规则细节、团队、参与方式与成本
- 第三方线只做一次精确词搜索；返回无关结果即把『零第三方覆盖』作为结论输出，停止搜索分支

## Stop conditions
- 内嵌数据与发布文章已交叉给出用户所需全部事实（数字、口径、规则、联系方式）
- 精确词搜索一次确认无任何第三方结果后立即停止搜索分支

## Verification
- 内嵌 JSON 的 generated_at、模型名、Elo 与博客正文数字互相核对一致
- 所有访问过的子页路由均来自 HTML/bundle 实际引用而非猜测（全程无 404 试探）

## Counterexamples
- 页面为服务端渲染，正文抓取已含完整目标内容 → 直接分析并停止，不必挖 bundle
- 搜索仅部分污染，精确词/第二页仍有权威第三方报道 → 第三方线应继续推进，而非只啃官网一手源
- bundle 高度混淆且数据走运行时 API 请求 → 静态解析 bundle 失效，应抓网络流量而非继续读 JS 文本
