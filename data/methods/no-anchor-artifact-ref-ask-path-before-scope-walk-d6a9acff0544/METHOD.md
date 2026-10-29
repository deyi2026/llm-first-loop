---
method_id: no-anchor-artifact-ref-ask-path-before-scope-walk-d6a9acff0544
name: no-anchor-artifact-ref-ask-path-before-scope-walk
description: 续跑上轮计划时，待办项按名引用的 artifact（文件/回执/记录）在本轮权威枚举里查无此名、且 in-hand 输出没有任何路径锚点时，继续换 scope 遍历目录树不会缩小『它在哪』这个未知量。把『该引用是否有当前 provenance』当作第一未知量：先在 status 全量展开/回执/索引里找正向锚点，每个 plausible scope 至多做一次有界 name 检索；仍无锚点即停止枚举，向用户列出已查 scope 并索要完整路径或确认并入/放弃。与 remeasure 类卡片互补：那管范围数字对账，本卡管具名对象存在性追查的成本上限。
aliases: 上轮提到的文件找不到了还要不要翻目录, 找不到的文件直接问用户要路径, 幽灵文件别满盘扫, 待办引用的产物查无此名先问路径, 记忆里的文件名没有出处就别再换目录找
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:3e24aff2-8af5-497f-882a-a249bcc66acd:385:87ee18ae484eab67d795
evidence_refs: learning:learn:f1e03542b9bf
created_at: 2026-10-28T13:22:33.584286+08:00
updated_at: 2026-10-28T13:22:33.584286+08:00
---
## Trigger
跨轮续跑先前计划/建议时，某待办项按名字引用一个 artifact（如某结果文件、回执），但本轮实测的权威清单（quotepath 安全的 git status 全量展开、tracked 树检索）中查无此名，引用只来自上轮对话记忆、且当时就未给出可定位路径。

## Discriminator
扩大搜索前先数『正向锚点』：in-hand 输出（status 全量展开、任何回执、索引、上轮成功输出）中是否出现过该名字的路径样例。锚点=0 且一次 scoped name 检索（如仓库内一次 find -name）未命中 ⇒ 该引用当前无 provenance，再枚举其他目录树不产生新判别信息，只会扩散搜索空间。

## Short path
- 用当前权威枚举（status 全量展开 / tracked 检索）对账计划里的具名对象；命中 → 按该路径执行原处置
- 未命中 → 检查 in-hand 回执/索引/上轮成功输出是否含该名字的路径样例（正向锚点）
- 每个 plausible scope 至多做一次有界 name 匹配（一次 find/ls），不进入逐目录树遍历
- 仍无锚点 → 停止枚举，向用户报告已查 scope 清单，索要完整路径或确认该 artifact 已并入其他文件/应放弃
- 用户给出路径后先验证存在性（ls/读回执）再执行原计划的处置动作

## Stop conditions
- 在任一 in-hand 输出中找到该名字的路径样例（转为沿 provenance 执行，不再问用户）
- 用户提供完整路径，或确认该 artifact 已并入其他文件/放弃留存
- 已对每个 plausible scope 完成一次有界检索且均无命中——此时唯一合理动作是提问，不是再枚举新 scope

## Verification
- 向用户报告的『已查 scope』与实际执行过的检索逐条对应，不虚报覆盖面
- 用户给出路径后先 ls/读文件确认存在且内容匹配引用语义，再执行处置（复制/移动/入库）

## Counterexamples
- 名字出现在任一回执、索引或 untracked 列表里 → 已有正向锚点，直接沿锚点走，不必问用户
- artifact 属于有命名规范的 store（如 receipts 目录）→ 先解析命名方案定向构造路径，而非问用户或树遍历
- 本会话内自己刚创建/引用的对象 → 不是记忆陈旧问题，检索自己近期输出即可定位
- 文件名是通用词（report.md 之类）会大量误命中 → 未知量是『哪一个』而非『是否存在』，枚举+身份确认仍然适用
