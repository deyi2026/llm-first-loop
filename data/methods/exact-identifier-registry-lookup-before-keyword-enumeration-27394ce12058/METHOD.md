---
method_id: exact-identifier-registry-lookup-before-keyword-enumeration-27394ce12058
name: exact-identifier-registry-lookup-before-keyword-enumeration
description: 当源 artifact 已给出精确可安装标识（npm 包名/插件名等）且该生态按名走注册表安装时，直接对注册表按精确名做一次元数据查询，用 repository 字段解析权威仓库地址，再用 README 特征集与源描述比对确认；不要把精确名降级成关键词组合去搜索引擎、GitHub 搜索或本地文件系统做宽枚举。尤其适用于泛化 token（品牌缩写、通用词）已污染普通搜索结果的场景：一次按名 O(1) 查询优于任何组合枚举。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:136b8530-addf-4ead-941f-0a53520c54d8:4:b0ffc302fcb24ea4d8dd
evidence_refs: learning:learn:970915df47d6
created_at: 2026-10-11T18:59:02.286147+08:00
updated_at: 2026-10-11T18:59:02.286147+08:00
---
## Trigger
源 artifact（文章/安装说明）已给出精确安装名或包名，当前未知量是该名对应的权威仓库/来源地址，且关键词搜索已被泛化 token（如 DS 汽车品牌 vs ds-bot 缩写）污染、命中率趋零。

## Discriminator
安装说明明确写出'在 dsh desktop 插件页输入: ds-bot'——即该生态存在以精确名为键的插件/包注册表；同时本机与文档显示 dsh 走 npm 分发（registry.npmjs.org/npmmirror）。这两个当时已知事实共同说明：按名查询注册表元数据即可解析 repository 字段，而任何关键词组合（ds-bot+dsh、ds-bot+dsh-plugin）只是宽枚举。

## Short path
- 从源 artifact 提取精确标识与生态：安装名 ds-bot、宿主 dsh、安装方式=按名进注册表；未知量=该名对应哪个仓库
- 确认该生态的注册表端点（dsh 为 npm 分发 → GET registry.npmjs.org/ds-bot）；未知量=注册表里该名的元数据
- 读元数据 repository 字段得到 GitHub URL；未知量=权威仓库地址
- 抓该仓库 raw README，与源 artifact 特征集（dsh 插件、持久化 Bot、自带 API Key）比对；一致即停止

## Stop conditions
- 注册表按名命中且 repository 字段给出 URL，README 特征与源描述一致 → 停止，如实区分'直接核验事实'与'特征匹配推断'
- 源 artifact 本身已直接印出完整仓库 URL → 只需验证该 URL，无需注册表查询
- 注册表 404 且文档无别名/镜像线索 → 才回退到 GitHub 关键词/代码搜索等宽发现

## Verification
- 最终输出 URL 与注册表元数据 repository 字段一致
- README 内容与源 artifact 描述特征逐条匹配，并分开陈述哪些是直接核验、哪些靠特征集匹配
- 未核验事实（如 GitHub API 403 限流未取 star 数、本机 dsh 版本与插件要求不符）明确标注，不冒充已核验

## Counterexamples
- 同名不同物：注册表命中项与源描述特征不符（如只是 demo 占位包 dsh-bot-demo-*）→ 不能仅凭同名认定，必须特征比对后再下结论
- 安装方式是直接给 git clone URL 或原文已印出仓库地址 → 直接走该 URL，注册表查询多余
- 标识只是模糊描述（'那个 dsh 的 bot 插件'）而无精确名 → 此时应先从源文档获取精确名，本方法不适用
- 注册表查询被 403 限流且无可用镜像 → 才允许回退到搜索引擎宽发现
