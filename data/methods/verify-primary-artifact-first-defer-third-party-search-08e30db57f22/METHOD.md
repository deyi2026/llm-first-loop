---
method_id: verify-primary-artifact-first-defer-third-party-search-08e30db57f22
name: verify-primary-artifact-first-defer-third-party-search
description: 核实/审计一个有权威原件（GitHub 仓库、官网、规范、数据集）的项目时，首次抓取成功返回实质正文，就已回答'是否存在/是否官方'；剩余未知量几乎都在原件内部（代码、文档、测量数据）。此时应直接深入原件（clone 后读 pinned 副本），把宽搜索推迟到出现原件无法回答的外部性未知量（口碑、独立评测、镜像定位）再做。同时不要对 volatile 的网页副本分块重读'补全'即将被 pinned 克隆覆盖的同一文本。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9571992a-d742-4a48-824b-b1f635b8674f:4:30fecb5ccb8c641561c7
evidence_refs: learning:learn:eef4615e25c5
created_at: 2026-10-07T08:18:18.582835+08:00
updated_at: 2026-10-07T08:18:18.582835+08:00
---
## Trigger
任务是核实/审计某个可直接访问的权威 artifact（仓库/官网/论文/数据集），且对该 artifact 的首次抓取已成功返回含具体可证伪宣称的实质正文

## Discriminator
抓取回执当时已显示：权威原件存在、来自官方 namespace、含真实 README/规范正文。此时存在性与官方性已答；第三方页面无法提供比原件更高的验证权威；且证据元数据标注 version_policy=volatile/version_token=null，若下一步计划 clone，则网页完整版是弱版本证据，clone 的 pinned 副本严格更优

## Short path
- 直接抓取权威 URL，确认存在性与宣称内容（此时不发起第三方搜索）
- 未知量='宣称是否有代码/数据支撑' → 立即 clone 取 pinned 副本（文件树、README.md、docs、原始测量数据），不再分块重读 volatile 网页版
- 逐条宣称对照源码/原始数据核实，只读宣称涉及的文件
- 仅当出现原件答不了的外部性未知量（社区评价、独立基准、镜像）时，才发起带明确 scope 的搜索
- 每条结论标注来自原件的哪份证据，覆盖完用户问题即停止

## Stop conditions
- 用户问题所需事实均已由 pinned 原件证据核实，写出逐条对照结论
- 原件不可得（抓取失败/404/付费墙/反爬）——切换为搜索定位镜像或替代权威源
- 剩余未知量被证实为外部性问题（口碑/独立评测）——转入限定范围搜索

## Verification
- 最终报告中每条核实结论都能指回原件内可复核的文件/数据（如 docs 下的原始测量 JSON、源码行号），而非第三方转述
- 检查是否存在先于原件获取的宽搜索轮次，以及其结果是否被最终结论引用——未被引用的搜索即浪费轮次
- 同一文本不应既从 volatile 网页副本完整读一遍、又从 pinned 克隆再读一遍

## Counterexamples
- 首次抓取失败/被拦（404、付费墙、反爬）——搜索是正确的第一动作，用于定位镜像或官方替代入口
- 用户问题本身是外部性的（'这项目口碑如何/有没有负面评价/独立评测'）——第三方来源就是目标内容，搜索是主线而非绕路
- 抓取只返回空壳/落地页、无可证伪宣称——当时判别事实不足，需搜索补上下文，不应套用本方法
- 对象不是可 clone 的代码/数据 artifact（如新闻宣称、事件）——'深入原件'无对应动作，需按证据等级另行检索
