---
method_id: deterministic-404-is-an-answer-pivot-to-canonical-candidate-daaa7d2b6d35
name: deterministic-404-is-an-answer-pivot-to-canonical-candidate
description: 核实'具名资源'类说法（GitHub org/仓库、URL、包名）时，对说法给出的标识符探测返回确定性 404 后，不要把它当访问故障做换 UA/多轮回退重试；把 404 记为'该标识符不存在'的一次性反证并冻结该分支，立即转向同轮搜索里已出现的平台规范候选（描述精确匹配的仓库/端点），再沿其自带 provenance 边（官方站点、给 AI 的聚合文档、api.github.com 等权威元数据端点）补齐其余待核事实。搜索空间从'猜测 URL 怎么抓通'收缩为'一个已命名的规范候选是否坐实其余说法'。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:62ab768f-1c8b-4c05-baa1-c1ac5d5dd147:18:1b6d4a990ca0b546c3b0
evidence_refs: learning:learn:c966a34c028c
created_at: 2026-09-20T16:56:21.878427+00:00
updated_at: 2026-09-20T16:56:21.878427+00:00
---
## Trigger
事实核查/验证任务中：说法包含具体标识符（如文章声称的 GitHub org/仓库名），对该标识符的抓取返回确定性 HTTP 404；或首轮定向搜索已返回与实体描述精确匹配的平台规范候选，而尚未探测该候选。

## Discriminator
当时已可见的两条事实：① 抓取回执明确是 HTTP 404（'资源不存在'的确定性状态），不是 timeout/403/429/5xx 等瞬态或访问层错误——换 UA、curl 回退都不可能改变存在性判定；② 同轮搜索结果第 1 条已给出平台规范标识符及与目标实体完全吻合的官方描述（HiThink-Tech/Financial-API：'同花顺官方 A股金融数据服…'），窄下一跳在 404 之前就已在手。

## Short path
- 对说法中的具名标识符做一次抓取以取得存在性反证（只做一次，不做 UA/重试变体）
- 收到确定性 404 → 直接记为'该标识符不存在'的证据，冻结这条猜测分支
- 转向搜索结果中的规范候选，抓其本体 README 与权威元数据端点（如 api.github.com/repos/...），一次性取得创建时间、stars、license、活跃度
- 沿候选自带的 provenance 边补齐其余事实：README 里的官网链接、站点给 AI 的 llms.txt/快速接入文档
- 逐条对照原说法，标记为 已证实/需修正/未验证 三态，停止

## Stop conditions
- 说法中每个可核事实都已映射到权威来源，或已显式标记为'未验证'，无新增未知量
- 具名标识符的存在性已由确定性状态码判定并记录，规范候选已由平台元数据/官方文档证实

## Verification
- 最终报告同时引用两类证据：404 回执（用于修正'标识符'说法）与规范候选的原文/元数据（用于证实其余说法）
- 报告区分 已验证/需修正/未验证 三态，未清点的项目（如端点/工具总数）显式标注，不默认当作已证实
- 检查对同一确定性 404 目标没有发出第二次带参数变体的重试

## Counterexamples
- 返回 403/429/5xx/timeout：这些可能是 UA 拦截、限流或瞬态故障，轮换与重试是合理的，本方法不适用
- 搜索结果中没有与实体描述匹配的规范候选：404 只说明'说法暂未证实'，此时才需要扩大发现（平台内搜 org/用户、站内搜索），而非立即下结论
- 目标站点对爬虫返回伪装 404（反爬 cloaking），而搜索快照强表明页面存在：应换权威替代端点（API、缓存、镜像）再判定，不能直接判'不存在'
