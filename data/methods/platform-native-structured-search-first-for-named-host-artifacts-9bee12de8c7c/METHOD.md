---
method_id: platform-native-structured-search-first-for-named-host-artifacts-9bee12de8c7c
name: platform-native-structured-search-first-for-named-host-artifacts
description: 用户目标中明确点名某托管平台（如 GitHub）作为工件来源（找/评估仓库、skill、包）时，第一发现层应直接用该平台原生结构化搜索 API，而非通用网页引擎：后者通常只返回首页/镜像/门户级噪声。关键词矩阵要中英双语——最好的中文候选（公众号排版/发布类）往往只在母语词百分号编码的查询里出现；非 ASCII 不编码会得到空集。用 curl+jq 只留 full_name/stars/description 控制上下文；读 README 走能解析默认分支的 API 端点，避免猜 raw 路径 404 与解码错误；最后对照本地已有技能清单回答"适合我们"。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:dc641ca1-674e-4d59-a969-1b1782a23127:0:c9cf6f671037e99c8040
evidence_refs: learning:learn:243bc954467a
created_at: 2026-10-13T23:22:44.884682+08:00
updated_at: 2026-10-13T23:22:44.884682+08:00
---
## Trigger
任务以"在某平台(github等)上找/调研/评估某类工件(仓库/skill/包)"表述，且正在考虑或已执行通用搜索引擎查询；或搜索回执全部是首页/登录页/镜像站等门户级条目而非具体工件 URL。

## Discriminator
任务文本在 t0 就显式含目标平台名（可观察：用户原话写了 github），平台的仓库搜索 API 即权威索引；辅判据：网页搜索回执 9 条全是 github.com 首页/登录/中文镜像，零 repo 级链接；curl 循环回执中某组查询标题下 0 行结果而其他组正常，即编码/分组错误而非无内容。

## Short path
- 从用户措辞提取 点名平台+工件类型+意图动词 → 直接调用平台结构化搜索 API（q + sort=stars），跳过通用网页搜索首轮。
- 构造小批量查询矩阵：英文能力词(skill/writing/publish) + 母语平台名(公众号/知乎/写作等，百分号编码)，一次 curl 循环跑完，jq 只输出 full_name/stars/description/更新日期。
- 按回执分支：某组 0 结果或 total_count 荒谬大(>5万) → 先怀疑 OR 分组/未编码并修复，不新增查询维度；某组候选已被覆盖 → 停止扩组。
- 对 stars+描述匹配的前几名仓库，用解析默认分支的 API 端点(如 /repos/{o}/{r}/readme) + UTF-8 locale 读 README，核对依赖与运行要求。
- 候选与本地技能清单交叉比对（重复/缺口），输出带星数、依赖、适配结论的分层建议表并停。

## Stop conditions
- 候选表已覆盖用户需求的主要分层且各项均有 API 实查星数/依赖/适配结论，停止发现。
- 平台 API 限流或鉴权失败：至多一次回退(site: 定向网页搜索)，停下说明局限。
- 用户术语存在两种解读（如"文章发表"=学术投稿 vs 公众号/博客发布）：列出区分项并带两个方向各给首选，停止继续扫仓库。

## Verification
- 每个候选的星数/描述/依赖来自平台 API 回执（查询时数据），不是搜索引 snippet。
- 母语词查询 URL 确认已百分号编码且 total_count>0，结果集中确有母语命名仓库。
- 最终建议显式对照本地已有技能链，指出每个新候选填补/重复的环节，不与现有功能重复推荐。

## Counterexamples
- 目标是不绑定特定平台的开放网络信息（找文章/答案本身）→ 通用网页搜索仍是主路径，不适用。
- 用户已给出具体仓库名/链接 → 跳过发现层直接读该仓库。
- 网页搜索首轮已直接列出具体 repo/awesome-list URL（非门户噪声）→ 直接沿链接走，无需切 API。
- 需要的是仓库内全文代码/文件搜索而非仓库级发现 → 用 code search API，本方法的 repository search 维度失效。
