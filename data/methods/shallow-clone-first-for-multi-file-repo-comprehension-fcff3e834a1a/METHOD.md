---
method_id: shallow-clone-first-for-multi-file-repo-comprehension-fcff3e834a1a
name: shallow-clone-first-for-multi-file-repo-comprehension
description: 任务要求深入理解/对照一个公开 git 仓库（未知量横跨多文件：架构、调度、策略源码、工程取舍），而 README 网页摘录已出现句中截断、文件树 API 403 时，把 git clone --depth 1 作为唯一获取动作尽早（可后台）执行；网页摘录仅作定向，不再逐 URL 猜文件、UA 轮换重试或重复抓取已抓页面。clone 期间并行读本方工作区索引文档补齐对照侧。本集从首次 README 截断到最终 clone 之间插入多次散射式抓取/枚举（含重复抓取同页、API 重试），而 clone 一次即取得全部一手文件，正是最终纠偏（二手文章口径≠仓库事实）的基础。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:4262a65a-bd51-4405-bed5-57af83e2e1ab:4:b732016ee4384ffcad2d
evidence_refs: learning:learn:6919ee24bc56
created_at: 2026-10-21T23:15:03.051521+08:00
updated_at: 2026-10-21T23:15:03.051521+08:00
---
## Trigger
任务的外部目标是公开托管在 git 平台的代码仓库，且所需理解超出 README 级单事实（点名架构/机制/源码取舍等多文件未知量）；已出现网页摘录截断、或文件树 API 被限流/403 等通道有损信号；本地具备执行 shell/git 的能力。

## Discriminator
首次 README 摘录在句中/词中截断（配置项名只写到一半）——extract 通道有损的直接证据；任务未知量横跨多个文件而其路径未知（raw 单文件抓取可行但无法枚举树）；目标是公开 GitHub repo 且本地可执行 clone。这三条在当时已同时可见，足以把'继续逐 URL 抓取/枚举'缩成'一次 shallow clone 获得全部权威文件'。

## Short path
- 从用户目标判定外部目标的深度档位：整仓多文件理解 → 获取方式首选 clone，而非网页逐页摘录
- 抓一次 README 作定向；观察到摘录截断 → 确认 extract 通道不足以覆盖未知量
- 立即启动 git clone --depth 1（慢则后台执行），把未知文件集变成本地可 grep/read 的树
- clone 期间并行读本方工作区索引文档（docs 索引、子项目 README），补齐对照侧权威事实
- 从 clone 内按 README/doc 索引点名读关键文件（调度/策略/投机解码等），把二手文章的每个关键数字与机制逐条对到一手文件
- 每条借鉴/结合建议同时锚定外部文件证据与本地下落点后落盘文档，停止

## Stop conditions
- 所有将写入结论的外部机制描述均已从本地 clone 的一手文件复核
- 二手来源的每个关键数字均已判定'仓库内有出处/无出处'并明说分歧
- 每条建议都同时具备外部一手证据与本地子项目落点，文档已落盘

## Verification
- 结论中的外部机制引用能在 clone 内具体文件（路径/章节）复核
- 与二手文章冲突处已按一手仓库裁决并显式标注
- 无对已抓取 URL 的重复抓取、无对失败 API 的同参重试

## Counterexamples
- 只需 README 级单事实（license、支持模型列表、单条配置含义）→ 单次定向抓取比 clone 便宜
- 路径已知的单个文件需求 → raw 直链即可，无需整仓
- 仓库私有/不可达、网络只允许 HTTP 摘录、磁盘或流量禁不起大仓 → clone 不可行，退化为逐文件抓取或 --filter=blob:none 部分克隆
- 目标是文档站/网页快照而非 git 仓库 → 无 clone 对象，此法不适用
