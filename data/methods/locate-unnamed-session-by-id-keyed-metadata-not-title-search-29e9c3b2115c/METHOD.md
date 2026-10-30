---
method_id: locate-unnamed-session-by-id-keyed-metadata-not-title-search-29e9c3b2115c
name: locate-unnamed-session-by-id-keyed-metadata-not-title-search
description: 用户按主题词找不到某个会话、但上下文证明它存在且近期活跃（并发写入、交接提及）时，不要换关键词反复语义搜索，也不要全工作区枚举文件名：会话标题通常冻结在起源首条消息（如贴进来的 URL），后来演化的主题不会回写标题，按演化主题的语义检索结构性失效。改为按身份定位：从既有回执的结构证据（topology 的 parent/child_session_id、目录清单里的 <uuid>.json、归档 manifest 的 session_id 字段）提取候选 UUID，再直读会话注册表元数据（标题/首条消息/created_at/updated_at）逐个确认，用首条消息+最近更新时间锁定身份，并把“标题是链接/旧问题”作为用户搜不到的原因回报。
aliases: 用户说找不到某个会话怎么定位, 会话标题是链接搜不到, 按会话ID读元数据找会话, 找正在并发写入的那个会话是哪个, 会话标题和后来内容对不上怎么找
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:cab051cc-c0ca-4a09-b848-6d4a00ec0ffe:2889:aa4c98ef0accc5678673
evidence_refs: learning:learn:71d8e73381e0
created_at: 2026-10-30T16:18:14.665257+08:00
updated_at: 2026-10-30T16:18:14.665257+08:00
---
## Trigger
需要定位一个无法按主题词检索到的会话/对话记录：用户明确说“找不到这个会话”，但证据（压缩段、并发写入观察、交接提及）表明该会话存在且分钟级新鲜。

## Discriminator
检索扩散前已可见的事实：①用户自己的主题检索已失败——这本身证明标题/主题通道失效，继续换词是同通道重试；②既有回执已展示会话按 UUID 落盘且可定位（snapshot 路径形如 data/compaction_snapshots/<uuid>/、event_logs/<uuid>.jsonl 命名、topology 记录含 parent_session_id）；③压缩段记载“对方会话 N 分钟前仍在写”——活性可用 updated_at/mtime 做筛选维度。

## Short path
- 把“找会话”的未知量改写为“哪个 UUID”：从已取回的结构证据（topology、目录清单、归档 manifest 的 session_id）提取候选；不足时对会话存储目录做一层有界列举（按扩展名过滤），禁止全工作区文件名枚举（只会命中日志/备份噪声）
- 对每个候选直读注册表元数据文件（title、首条消息、created_at、updated_at）——未知量收敛为“哪个候选的起源与活性匹配”
- 标题若是 URL/无关短语而首条消息是起源问题 → 判定“标题冻结在起源”，即用户按主题搜不到的机制原因；用首条消息+updated_at 双证据确认身份
- 向用户回报 id、标题、首条消息摘要与“为什么按主题搜不到”，身份闭合即停

## Stop conditions
- 已从注册表元数据确认目标会话身份（UUID+标题+首条消息+最近更新时间），并向用户解释了按主题检索失败的原因

## Verification
- 候选 UUID 与结构证据（topology parent_session_id / 目录清单）一致
- 元数据 updated_at 与观察到的并发写入时间窗吻合
- 首条消息内容能解释标题的来源（标题=首条消息的 URL/摘要）

## Counterexamples
- 标题本来就准确、用户只是记错关键词 → 主题或全文搜索即可命中，无需绕结构证据
- 会话库很小且检索工具支持消息全文内容搜索 → 直接按内容搜更快，身份通道多余
- 目标是文档/工单等标题随内容维护的记录 → “标题冻结”解释不成立，普通检索适用
