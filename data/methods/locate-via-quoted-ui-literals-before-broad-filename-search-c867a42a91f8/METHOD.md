---
method_id: locate-via-quoted-ui-literals-before-broad-filename-search-c867a42a91f8
name: locate-via-quoted-ui-literals-before-broad-filename-search
description: 用户请求原文引用界面可见文本（面板名、按钮文案、卡片字段等）要求改 UI 或数据展示时，先用这些高区分度字面量在源码根内做内容 grep 定位实现，而不是先做全库文件名搜索：文件名搜索匹配不到内容标签，还会扫过 evals/node_modules/chrome-profile 等生成物树，产生纯噪音甚至超时。定位到组件后，字段存在性沿『前端 api 类型层 → endpoint 字符串 → 后端路由 → store 投影』一条链一次查清。
aliases: 按界面上的按钮文案去源码里搜, 文件名搜界面文字全是噪音, 别扫 node_modules 生成目录, content grep 定位组件, store 投影一条链查清, 这个按钮的代码在哪
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:073925d0-5718-467d-8ea0-bd5d603daeb9:1:9e3300536577561607c7
evidence_refs: learning:learn:32877aa46dd6
created_at: 2026-10-13T21:26:47.937952+08:00
updated_at: 2026-10-23T05:52:04.749434+08:00
---
## Trigger
任务请求原文中出现界面可见的专属标签/功能名（如面板名、按钮文案、卡片字段），需要在代码库中定位并修改其实现；或全库文件名搜索已返回生成物噪音、发生超时

## Discriminator
请求原文是否自带 1~2 个高区分度字面量（专属功能名如『知识管理/学习通道/经验卡片』，而非『确定/设置』类通用词）；以及仓库根是否含大体量生成物目录（evals/、node_modules、浏览器 profile），使全库文件名搜索注定噪音+超时。二者同时成立时，内容键 scoped grep 是唯一低代价入口

## Short path
- 从请求原文抽取 1~2 个专属功能名字面量；先 ls -d */ 一次确认前端/后端源码根（如 webui/、src/）
- 对源码根 grep 内容键（『知识管理/经验』等）→ 直接命中目标组件（KnowledgePanel/LearningPanel/Sidebar）及其挂载点，读取确认当前布局
- 数据字段类需求：grep 字段名（use_count/last_used/usage）于前端 api 类型层确认缺失，再沿 endpoint 路径字符串 grep 后端路由 → store catalog 投影
- 实现后以组件测试+构建收口；内容键已高精度命中即停止扩大搜索，不对同义词变体重复全库枚举

## Stop conditions
- 已读到渲染目标 label 的源组件及其挂载布局，且所需字段在前端类型与后端 store 两侧的存在性都已确认
- 内容 grep 一次高精度命中目标源文件后，不再扩大搜索范围

## Verification
- 读命中文件确认它确实渲染/定义该 label（而非测试快照或文档），最终改动落在这些文件且相关组件测试与后端 endpoint 测试通过

## Counterexamples
- label 集中在 i18n 资源包或构建期生成，源码内无字面量：应改查资源文件/生成器，『源码内字面量』假设失效
- 字符串过于通用（『确定』『设置』）命中成百上千处：换用相邻专有词组合或组件命名约定，而非继续字面量 grep
- 目标本就是一个已知文件名/路径（配置文件、迁移脚本）：文件名/路径搜索才是正确入口，本方法不适用
- 小仓库且无生成物目录：全库搜索代价低且可直接用，无需先做源码根限定
