---
method_id: exact-identifier-then-namespace-verification-ceabd1d5ad03
name: exact-identifier-then-namespace-verification
description: 当一次 discovery 检索已经产出目标的确切标识符（精确制品名）和权威命名空间线索（官方域名、发布组织/账号）时，在目标平台（GitHub 等）定位必须走『精确标识符搜索 + 命名空间一致性验证』，而不是用泛化关键词（原始短词+genre）按热度枚举同名候选。身份用跨源一致性确认：官方域名 ↔ owner 组织名 ↔ 发布方署名。平台 API 被限流时，优先回读此前已捕获的证据而非重试同一端点。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:136:be5e004800e5c821f22f
evidence_refs: learning:learn:61a262caf5b0
created_at: 2026-09-18T10:39:51.934568+00:00
updated_at: 2026-09-18T10:39:51.934568+00:00
---
## Trigger
平台定位类任务（"找 XX 的仓库/项目"）中，已有检索结果明确包含确切制品名与官方域名/发布方命名空间，但下一步动作是按泛化关键词在目标平台枚举候选（尤其按 stars 排序）。

## Discriminator
进入泛化平台搜索之前，成功检索结果里已同时出现：精确名 'Atria-Dawn-Preview'、官方域名 'api.atria-asi.ai'、发布方（上海人工智能实验室）与 HF 仓库名。这一当时已知事实把 GitHub 候选空间从『所有含 atria 的仓库按 stars 枚举』缩为『名称精确匹配 Atria-Dawn-Preview 且 owner 与官方域名一致的仓库』，无需任何新信息。

## Short path
- 渠道回退重搜（code→general）直到拿到确切制品名与官方域名——这是必要的 discovery，保留
- 在 GitHub 用精确标识符搜索（q=Atria-Dawn），未知量：官方仓库是否存在、owner 是谁
- 用命名空间一致性验证身份：owner 'atria-asi' 与官网域名 'api.atria-asi.ai' 字面一致，排除同名无关项目（如高星 TUI）
- 直接抓 raw README 满足分析所需的定位/评测/部署/许可证内容；仅当缺关键素材时定点补抓一次官方发布物（HF/官网）
- 仓库详情 API 403 限流时不重试：回读先前 GitHub 搜索 JSON 中已捕获的同一仓库条目取元数据（stars/language/created_at）
- 身份+内容双确认后停止发现，进入分析

## Stop conditions
- 已定位 owner 与官方命名空间一致的仓库，并取得 README 与仓库元数据
- 分析所需事实（是什么、含什么、评测、限制）已由权威来源覆盖
- exact-name 搜索 0 命中且官方渠道无平台指向——此时才退回泛化枚举

## Verification
- owner 名与官方域名/发布组织字面一致，或能从官方页面互链到该仓库
- 仓库内容与独立发布物（HF 权重页、官网）互相印证同一制品
- 被排除的同名候选与官方命名空间无任何关联（域名、组织、署名均不一致）

## Counterexamples
- discovery 未产出任何确切名称或官方域名（只有'某实验室的新 agent 模型'式模糊描述）：泛化关键词枚举是正确起点，本方法不适用
- 确切名是常见通用词且无官方命名空间可验证：exact-name 搜索仍大量碰撞，需枚举+发布方交叉验证
- 用户目标本身有歧义、可能指多个同名项目：泛化搜索结果集本身是澄清歧义所需的证据，应先向用户确认
