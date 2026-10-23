---
method_id: index-miss-on-fresh-artifact-verify-disk-ground-truth-69d205734f31
name: index-miss-on-fresh-artifact-verify-disk-ground-truth
description: 用户按精确名断言某个近期创建的 artifact 并询问其状态/效力，首次索引搜索未命中且回执 success 无错误、同一索引刚列出同目录其他近期文档时，不要换措辞或加通配符扩大枚举：先把『索引未命中』当作索引新鲜度问题的候选，用一次非索引层查询（pwd+ls/stat）证实或证伪存在性。索引/检索视图是缓存，不是存在性判据。命中后沿文件头部自声明、SoT 引用 grep、git 跟踪状态三个可审计事实回答效力类问题；凡要构造『文件在另一个工作区/本会话看不到』这类假设，必须先被 pwd/ls 证实才可作为中间结论推进。
aliases: 搜不到不代表文件不存在, 用 ls 直接看磁盘有没有, 刚建的产物检索不到, 索引缓存不是存在性判据, 索引没刷新
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:96d621f5-1690-49cb-8e4d-e05d75600791:210:c74287d7d5290da8b1f0
evidence_refs: learning:learn:899cc04c7bb5
created_at: 2026-10-11T02:48:25.932343+08:00
updated_at: 2026-10-23T05:53:11.621096+08:00
---
## Trigger
用户按精确文件名断言某个近期创建的 artifact 并询问是否生效/如何生效，首次索引类搜索未命中（回执为 success、非工具故障），且该索引对同一目录的其他近期内容仍然可见、能列出『最近文档』

## Discriminator
文件名内嵌与当前日期相同的日期戳（用户默认其刚落地）+ 索引回执 success 但精确名未命中 + 同一索引刚刚成功列出同目录其他近期文档 → 这是『索引落后于磁盘』的新鲜度签名，而不是文件不存在的证据；当时即可把候选空间从『全库变体搜索』缩成『一次磁盘 stat』

## Short path
- 首次精确名搜索未命中后，先解决唯一未知量『磁盘上是否存在』，不做变体/通配符/换索引的扩大枚举
- pwd 锚定当前工作区身份（防止后续误判『在别的 mirror/工作区』），随后 ls -la 直接 stat 目标路径，一次调用证实或证伪存在性
- 存在 → 读文件头部自声明（状态/SoT 归属/注入角色），grep SoT 真值源引用，git status 查跟踪状态；用这三条事实分别回答『是否生效』『是否需重启』『约束力来源』
- 磁盘也未命中 → 才升级到 event_stream/search_records 找创建 provenance（哪个会话、哪条命令、哪个路径创建过它）
- 每个用户问题都有了非索引层权威来源后即停止；不重复读取已读窗口（需补读时必须改变 offset/limit）

## Stop conditions
- 磁盘 stat 证实存在，且文件头部自声明 + SoT grep 零引用 + git 未跟踪状态已覆盖用户全部问题（生效/重启/遵守）
- 磁盘也未命中，且 event_stream/records 已找到创建 provenance 或确证从未创建，可向用户如实报告缺席

## Verification
- 存在性结论必须引用非索引层证据（ls/stat/全文读取），不得只引用 search 回执的『无匹配』
- 效力结论需三方一致：文件头部自声明 + SoT 真值源零引用 grep + git 跟踪状态
- 任何『另一个工作区/会话看不到』的假设必须先被 pwd/ls 输出证实，未证实前不得作为中间结论陈述

## Counterexamples
- 文件名不含日期戳、用户只是模糊探询（『有没有类似 X 的文档』）而非断言存在 → 未命中即真实缺席证据，扩大关键词搜索是正确路径，不适用本方法
- 搜索工具本身直接读盘（find/ls 类，无索引层）→ 不存在新鲜度问题，未命中即缺席，无需二次 stat
- 磁盘 stat 也未命中 → 本方法第一跳已用尽，应转入 event_stream/records 的创建 provenance 搜索，而不是反复 stat 同一路径
