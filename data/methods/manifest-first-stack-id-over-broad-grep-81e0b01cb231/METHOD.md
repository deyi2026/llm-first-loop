---
method_id: manifest-first-stack-id-over-broad-grep-81e0b01cb231
name: manifest-first-stack-id-over-broad-grep
description: 当未知量是'某项目/服务实际使用什么技术栈或版本'、且工作区可见大量生成产物（评测结果、浏览器缓存、node_modules、构建输出）时，先读声明式依赖清单（pyproject.toml/package.json/requirements）而不是全树按名 grep 框架名：按名 grep 会命中文档、评测副本与缓存中的提及而被污染（本集首轮框架特征 grep 只命中 chrome-profile 缓存，被迫重搜）。两次 manifest 读取即可同时回答前后端栈，再用一个使用点交叉确认。对第三方文章的事实主张，则用权威注册表（如 PyPI JSON）核对版本与开发状态，而非转述。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:32:344727aac1edcb4b4da2
evidence_refs: learning:learn:87fa6b181841
created_at: 2026-09-17T16:59:09.009037+00:00
updated_at: 2026-09-17T16:59:09.009037+00:00
---
## Trigger
需要判断某个代码库/服务真实使用的技术栈、框架或版本来评估相关性，且首轮目录浏览已显示工作区含 evals/、结果 JSON、缓存或依赖目录等大量生成产物

## Discriminator
该未知量属于'声明式身份'类问题，其权威答案位于依赖 manifest 而非任意文本提及；同时首轮 ls 已可见 evals/ 与根目录大量结果文件，预示全树按名 grep 会被生成物污染——这两点在当时已可观察，足以把'全库搜框架名'缩成'读根 manifest + 前端目录 manifest'

## Short path
- 读取声称来源（文章/链接），提取待核主张（版本号、成熟度判断）与涉及的技术名
- 对第三方主张用权威注册表元数据（如 PyPI JSON：最新版本、Development Status classifier）核对，解决'文章是否过时或夸大'
- 对'本项目用什么栈'：做深度受限的 manifest 定位（find -maxdepth 并排除 node_modules/evals/缓存/工作树副本），直接读根 pyproject.toml 与前端目录 package.json
- 用一个真实使用点（服务入口代码或 API 文档中的实际调用）确认 manifest 反映的是目标服务而非无关副本
- 两类未知量均由权威来源（注册表 + manifest + 使用点）证实后立即停止发现，进入综合评价

## Stop conditions
- 文章/声称的关键事实已与权威注册表核对完毕（版本、开发状态）
- 前后端技术栈已由 manifest 声明加至少一个使用点交叉确认，无需再扩大搜索

## Verification
- manifest 声明的依赖与服务入口/文档中的实际用法一致（例如鉴权/上传/SSE 端点确由所声明框架构建）
- 最终结论中每个事实可追溯到注册表元数据或 manifest，而非宽搜索的偶然命中
- 若 grep 结果仅来自缓存/评测副本目录，视为污染信号而非证据

## Counterexamples
- 问题是行为层面的（SSE 如何实现、鉴权流程、某 API 怎么调用）——manifest 无法回答，必须读源码，本方法不适用
- monorepo 中根 manifest 不覆盖目标服务——需先定位该服务自己的 manifest，否则误判技术栈
- 问题本身就是'哪些文件提及/引用了 X'（溯源类未知量）——全树 grep 才是正确工具
- manifest 由脚手架生成或与 lockfile 长期不一致——需以 lockfile 或实际运行环境为准
