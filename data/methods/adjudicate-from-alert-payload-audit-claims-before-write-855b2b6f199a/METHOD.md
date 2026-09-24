---
method_id: adjudicate-from-alert-payload-audit-claims-before-write-855b2b6f199a
name: adjudicate-from-alert-payload-audit-claims-before-write
description: 自动化哨兵/告警触发后的裁定收尾法：先读告警自身 payload（命中表、点名文件）拿决定性事实，沿其显式指名的 artifact 单跳取证，用一次定向 grep 验证关联性；落盘裁定/结论文档前，对每句事实断言做字段级溯源审计——凡不能映射到本 episode 实际读过的 artifact 字段的断言（尤其是从先前对话继承的口头结论），要么一次直接字段查询证实，要么删除并按'字段不存在'如实记录，绝不从记忆回填。本次正是该审计抓住了先前'channel=web'的无据断言并在产出中显式修正，用 payload+单跳取证即可完成裁定，无需宽枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:1515:66471d6b9b73e0f5f8e7
evidence_refs: learning:learn:675028e7025e
created_at: 2026-09-22T16:13:45.278730+00:00
updated_at: 2026-09-22T16:13:45.278730+00:00
---
## Trigger
自动化告警/哨兵文件触发后需产出裁定或结论文档，且证据集中混有先前对话已断言、但未对照原始 artifact 的事实性 claim

## Discriminator
告警 payload 自身已含决定性字段（如 sid_hits={} 零命中 + new_topnames 点名唯一触发文件）；触发文件 head 已展示完整顶层 schema（question/resolved_at/final_answer/tool_names…）。任何不在已读字段集合内的继承断言（如 channel=web）即属无据，应在写前删或查证，而不是带入裁定

## Short path
- 读告警文件本体：命中表定'是否隔离击穿'，点名文件定'触发者是谁'，不做全目录枚举
- 沿 payload 点名的唯一 artifact 读 head/schema：真实用户会话（question+resolved_at+final_answer）→ 判 benign co-tenant 而非测试数据泄漏
- 用一次定向 grep 把告警标识符扫过 run 结果树，确认零关联，裁定事实即闭合
- 写入前 claim 审计：逐句把事实断言映射到本 episode 已读字段；无映射的继承断言做一次直接字段查询或删除，'字段不存在'按不存在记录
- 按预注册解读规则一次性套用已收集的聚合数（reward/tokens/rounds）写结论+归因+checkpoint，修正项在产出中显式标注

## Stop conditions
- 文档每句事实断言均映射到已读 artifact 字段或显式的'字段缺失'观察
- payload 零命中 + 点名 artifact 分类 + 关联性 grep 三者一致，可写 action=none
- 若命中表非空或 payload 自相矛盾，停止 benign 裁定，转升级调查路径

## Verification
- 重读写好的裁定/结论文档，逐句核对是否都有本 episode 实际读取到的字段支撑
- 确认无任何断言仅凭对话记忆支撑；被修正项在最终产出中显式记录（如本次 channel 修正）

## Counterexamples
- 继承断言涉及本地 artifact 不存储的信息（如操作者意图、外部系统配置）：单文件字段缺失不能证伪它，应在正确的存储做定向查询，而非直接删除
- 探索性草稿或内部笔记（非裁定级文档）：写时逐句审计成本大于收益，可延后到定稿前
- 告警 payload 含义不明或命中表非空：payload-first 顺序不再直接给出 benign 分类，须先升级调查再写文档
