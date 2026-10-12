---
method_id: exact-id-locate-store-backing-file-by-scoped-find-not-wide-grep-7b1f386ab61c
name: exact-id-locate-store-backing-file-by-scoped-find-not-wide-grep
description: 当结构化 record/event store 已按精确唯一 ID 命中但输出截断，需要权威完整记录时，不要立即做全仓文件枚举或多目录 content grep。先用 store 回执中的 kind 标签做浅层按名搜索（find 限定深度、按 kind/主题命名匹配）定位该 store 的落盘文件，再按精确 ID 过滤解析；索引型搜索返回确定性 no-match 时应换工具类（按名 find），而不是放宽同一工具的参数。大体积数据树禁止整仓 grep。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:1507:598ace40d16ce642c2ec
evidence_refs: learning:learn:11461a95fb6b
created_at: 2026-09-20T05:01:29.788333+00:00
updated_at: 2026-09-20T05:01:29.788333+00:00
---
## Trigger
结构化 record/event store 已用精确唯一 ID 命中（含 kind 标签与时间戳），但正文截断，需要权威完整记录；或索引型文件搜索对该 ID 返回确定性 no-match（success/无匹配，而非超时或报错）

## Discriminator
store 命中回执本身给出 kind 标签（如 evolution）与精确时间戳——权威副本几乎必然位于该 store 按类命名/组织的落盘文件中，可由仓库根一次浅层按名 find 直接定位；而 search_files 的确定性 no-match 表明其索引不覆盖该 store，重试更宽参数（pattern 从 *.json 放宽到 *）不会改变结果，只会在大树上扩散搜索

## Short path
- 持有精确唯一 ID 与 kind 标签时，从仓库根做一次浅层按名搜索（find -maxdepth 2~3，按 kind/主题命名模式）；未知量：该 store 的落盘文件在哪
- 对命中的候选文件按精确 ID 过滤解析（如逐行 json 解析比对 id 字段）；未知量：完整正文与元数据（status、evidence 引用、actions）
- 在同一 store 目录内读同类审计日志（review/exec）中同一 ID 的条目；未知量：审批决定、执行者与执行协议要求
- store 命中、权威记录、审批/执行日志三方字段一致即停止发现，转入执行阶段
- 仅当浅层按名搜索无果且无 kind 线索时，才升级为限定子树的 content grep（绝不整仓 grep 体积大的数据树）

## Stop conditions
- 权威记录全文已取得，且其 ID/时间戳/status 与 store 命中回执和审批日志逐字一致，后续执行所需字段（方案正文、evidence 引用）均来自该权威文件
- 浅层按名搜索命中唯一候选文件且按 ID 过滤成功
- 若确认 store 无文件落盘（纯 API/DB），则以 store 自身的字段展开重查为终点，不再碰磁盘

## Verification
- 解析出的记录 id/ts 与 store 命中回执逐字一致（防读到摘要或旧副本）
- 记录 status 与 review/exec 日志中的决定一致（executing/accepted 等状态对齐）
- 后续执行动作引用的字段确实取自权威文件而非截断摘要或过期片段

## Counterexamples
- store 为纯 API/数据库、无文件落盘：应改用 store 自身查询的更大 limit/字段展开，而非到磁盘找文件
- 目标 ID 大量出现在派生文档/变更日志中且无独立命名文件：按名搜索失效，需在浅层 find 先定位可能子树后再做限定范围 content grep
- 工作区很小且无结构化 store：直接宽搜成本可忽略，本方法无增益甚至多余
