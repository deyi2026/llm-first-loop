---
method_id: canonical-source-fetch-first-escape-degraded-keyword-search-channel-2ab461cf54b2
name: canonical-source-fetch-first-escape-degraded-keyword-search-channel
description: 核验具名项目（开源基准/工具/论文）属性时，先按 identifier 直取可预测权威源（github.com/<org>/<name>、arxiv.org/abs/<id>、官网），关键词网页搜索只作兜底；当搜索回执出现通道级退化——英文技术专名返回中文泛化页或词元撞车——立即停止换关键词重查，改换查询形态（精确全名+github/arxiv 限定、经论文页解析代码链接）。本集 8 次关键词搜索仅 1 次命中，而 org 已知的 canonical 直取全部成功；仅盲猜 org 的 URL 才 404，此时用一次精确名搜索解析即可。搜索通道正常且首查命中官方源时不必绕此弯路。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b08a5a88-4c62-47f9-84ed-c3cb191c061d:39:99f3c80eefe6a143fdf3
evidence_refs: learning:learn:4317406fc437
created_at: 2026-10-14T19:50:28.148440+08:00
updated_at: 2026-10-14T19:50:28.148440+08:00
---
## Trigger
需要核实若干『具名』工件（开源项目、基准、论文）的客观属性（是否开源、可否自跑、当前状态），且名字已在上文列出；或搜索后端首查回执已出现专名撞车/locale 错配的退化结果时。

## Discriminator
待核对象有精确 identifier，其权威源可预测（github.com/<org>/<name>、arxiv.org/abs/<id>）；且首份搜索回执已显现通道级退化——英文专名被解析成无关中文词元（如 MLE→最大似然估计、RE-Bench→动漫词条）——说明故障在通道而非措辞，换关键词变体无效。

## Short path
- 待核对象是上下文已列出的具名项目 → 逐名直取可预测权威源：已知 org 用 github.com/<org>/<name>，有论文用 arxiv.org/abs/<id>；未知量=官方仓库是否存在及 README 声明的开源/自跑状态
- 直取返回 404 → 不再盲猜 org/repo 变体；用一次『精确全名 + github/arxiv』原子查询或从论文页/官网的 code 链接解析真实仓库；未知量=canonical URL
- 首份搜索回执出现专名撞车或 locale 错配 → 判定该通道对此查询类退化，停用关键词变体重查；未知量=搜索通道是否还可用
- 每个名字获得一份权威回执（repo README/arXiv 摘要）即标记已核并汇总作答；未获得权威回执的项目在答案中显式标注『未核验』并停止补查

## Stop conditions
- 每个具名目标都有来自其 canonical 源的一份回执，或已在答案中显式标注为未核验项
- 同一搜索通道连续两份回执均为撞车/泛化结果 → 停用该通道的关键词变体查询
- 不再为已由权威回执回答的属性追加『再确认』式搜索

## Verification
- 核对回执 URL 与目标 identifier 匹配（org/repo 名或 arXiv id 一致），排除同名泛化页/内容农场页
- 答案中每条关键事实可指回一份已抓取的权威回执；无法指回的逐条标注未核验

## Counterexamples
- 开放发现型任务（名字未知，如『帮我找些能测 agent 的基准』）：无 canonical URL 可直取，关键词/广泛搜索是正确首选
- org 与项目名无规律且未知（如 terminal-bench 实际在 laude-institute 下）：先盲拼 URL 只会连续 404，应先经论文/官网链接解析仓库再直取
- 目标属性不在 README/摘要中（实际成本、跑通率、数据污染）：直取只能确认存在性与官方声明，不能当作该属性已核验，仍需实测或社区证据
- 搜索通道正常且回执直接命中官方源时：一次搜索即最短路径，不必先走直取-404-再解析的弯路
