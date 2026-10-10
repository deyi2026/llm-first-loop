---
method_id: dedupe-artifact-reads-against-in-context-coverage-pointers-0082d7e2b12a
name: dedupe-artifact-reads-against-in-context-coverage-pointers
description: 对同一 artifact 的第二次及以后读取，先做机械覆盖比对再发起：汇总当前上下文中该 artifact 各成功回执已展示的覆盖区间（显示 X–Y 行/共 N 行、range.complete、next_start、version_token）。目标区间已被完整覆盖→直接用既有内容，不发新 read；仅部分覆盖→只读缺口或从 next_start 续读；覆盖回执已被上下文裁剪丢弃、或 version_token/stat 显示文件已变→才允许重读（作为恢复/刷新）。『区间是否覆盖当前未知量所需内容』属模型判断，子集比对与指针续读是机械部分。本集存在完全落在前一回执 402–697 覆盖内的重读，run 级 duplicate_calls=7。该方法把『保险起见再读一遍』变成指针驱动的缺口续读，直接消除 post-sufficiency 重复读取。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e80a8cde-8a96-4b11-ad03-3f16341a32f5:67:53fdd2c353ed737183db
evidence_refs: learning:learn:32ea5aabee75
created_at: 2026-10-09T11:36:58.313460+08:00
updated_at: 2026-10-09T11:36:58.313460+08:00
---
## Trigger
需要对同一 artifact 发起第二次及以后的 read，且此前至少一条成功 read 回执仍在当前上下文中并声明了覆盖范围（行区间/总行数，或 range.complete=false + next_start）以及版本标识（version_token/stat）。

## Discriminator
发起 read 前可机械核对的事实：新请求区间 ⊆ 某条在案回执的已展示区间，或该 artifact 已报 complete/EOF，且 version_token/stat 未变 → 本次 read 不可能产生新信息；任一前提不成立（回执不可见、版本已变、存在并发写者）则比对失效，允许重读。

## Short path
- 读最近回执的覆盖元数据：行区间/共N行、range.complete、next_start、version_token
- 列出上下文中同 artifact 的全部在案覆盖区间，与目标区间求交集
- 目标区间已被完整覆盖 → 直接使用既有内容，跳过 read
- 仅部分覆盖 → 只发缺口区间的 read（从 next_start 或未覆盖行续读）
- 取得目标事实或 complete=true/EOF 即停止读取，不为『再确认』追加 read

## Stop conditions
- 所需事实已在上下文中，或读取回报 complete=true/EOF
- 继续读取不再产生未覆盖的新内容（候选区间 ⊆ 在案覆盖且版本未变）

## Verification
- 每次 read 前核对：请求区间与全部在案覆盖区间的交集判断（空=可读，非空=需说明缺口或豁免理由）
- 每次 read 后将新覆盖区间与 version_token 记入上下文，维护可核对的覆盖账本
- 抽检不变量：任何一次 read 的请求区间不应是早前在案区间的子集，除非覆盖回执已不可见或版本已变

## Counterexamples
- 早前覆盖回执已因长程上下文裁剪不在当前上下文——重读是恢复路径，本方法不适用
- version_token/stat 变化或存在已知并发写者（如另一 agent 正在同一仓库工作）——旧覆盖失效，必须重读并以新回执为准
- 需要不同视图或粒度（行号 vs 字节偏移 vs 结构化提取），或目标已换成另一 artifact——区间子集比对不适用
- 首次读取该 artifact：无在案覆盖可比对，方法不触发
