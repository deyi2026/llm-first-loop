---
method_id: manifest-first-stack-discovery-45cfedd8b434
name: manifest-first-stack-discovery
description: 在陌生仓库回答'本项目用什么技术栈/依赖'这类声明式事实时，先读清单文件（pyproject.toml、package.json、README/docs）而不是全树关键词 grep。本类仓库常含 evals 结果、浏览器 profile、缓存语料，关键词搜索会立即产生大量假命中，迫使事后重定向。清单是依赖事实的权威 provenance；只有当问题从'是否使用/什么版本'变成'怎么使用'时，才收窄范围搜代码。含 evals/、data/ 等生成物目录的仓库尤其应跳过内容级宽搜索。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:32:344727aac1edcb4b4da2
evidence_refs: learning:learn:87fa6b181841
created_at: 2026-09-17T16:59:35.765703+00:00
updated_at: 2026-09-17T16:59:35.765703+00:00
---
## Trigger
需要在未探索的代码库确认 web/框架/依赖技术栈（例如评估某外部技术对本项目的真实相关性），且定位性 ls 已能看到 README、docs、evals 等入口结构；待答问题属于'用没用、什么版本、什么构建工具'这类由声明文件权威回答的事实

## Discriminator
定位 ls 的输出本身：根目录呈现 README/docs/evals/data 等结构，说明（a）依赖问题的权威答案在 pyproject/package.json 等清单而非任意文件内容；（b）evals/ 目录预示存在结果缓存与 profile 数据，全树关键词 grep（如搜框架名）必然被污染——这两点在发起宽 grep 之前已可从目录名直接读出

## Short path
- ls 根目录，识别清单文件与 README/docs 入口——未知量：这是什么项目、技术栈在哪里声明
- 读后端依赖清单（pyproject.toml 或同类）——未知量：服务端框架与版本约束
- find -name package.json 排除 node_modules 定位前端清单并读取——未知量：前端框架、构建工具、关键库
- 仅当清单不足以回答时，将 grep 限定在 src/ 等源码目录内、按清单中的包名定向查用法或入口——未知量：实际使用方式
- 清单事实与外部权威源（如 PyPI 元数据）均已直接读到后停止，进入综合判断，不再枚举文件树

## Stop conditions
- 后端与前端清单均已直接读到，足以回答用户提出的适用性/相关性问题
- 最终结论引用的每个技术栈事实都锚定到具体清单行或文档行，无未解未知量

## Verification
- 抽查结论中的依赖事实是否与清单行一致（如版本约束确实出现在 pyproject.toml 中）
- 确认没有任何结论建立在 eval 结果、chrome-profile、缓存语料等目录的 grep 命中上
- 若清单与 README/docs 描述冲突，以清单/实际入口为准并注明

## Counterexamples
- 问题问的是'某框架怎么配置、怎么调用'而非'是否使用'——清单不回答用法，必须读源码与配置，宽一些的代码搜索是正当的
- 依赖仅作为可选 extra 或传递依赖出现在清单中——清单命中不等于主技术栈，需再查实际 import 与服务入口
- 无任何清单的脚本集合/notebook 仓库——不存在声明式 provenance，此时只能做内容级发现
- 清单是生成物或按环境多份并存——单一根清单不足以定论，需找真实构建入口
