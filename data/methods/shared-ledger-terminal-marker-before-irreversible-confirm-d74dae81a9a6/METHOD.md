---
method_id: shared-ledger-terminal-marker-before-irreversible-confirm-d74dae81a9a6
name: shared-ledger-terminal-marker-before-irreversible-confirm
description: 极简推送类指令或准备重跑任何由最终 confirm 把关的不可逆外部动作（发布/提交/撤销）时，若多个会话（排期班次+交互会话）共享同一份逐阶段追加的阶段台账，第一未知量不是『怎么跑流水线』而是『是否已被并发写者提交』：先读台账 log 尾部的 terminal 标记（submitted+时间戳+内容身份），标记存在则不 prepare 不 confirm，转外部唯一性核验。本集在 preview 完成后才从台账读到并发会话已 submitted，靠克制未点确认才拦下重复发布；正确路径是先读这一个文件。
aliases: 推送前先查session json有没有submitted, 确认发布前看别的会话提交没, 排期会话在推人还能不能再发, 同稿重复发布拦截, 已备好发布页但台账已submitted, 并发会话防二次发布
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:d01dc57e-09db-46b2-ba95-be8830903b10:0:019f2c33b1a78e192f51
evidence_refs: learning:learn:a5520cfed219
created_at: 2026-10-31T13:55:32.052859+08:00
updated_at: 2026-10-31T13:55:32.052859+08:00
---
## Trigger
收到极简推送/发布类指令且无活动 goal，或准备执行任何由最终确认按钮把关的不可逆外部动作，同时环境存在跨会话共享的阶段状态台账（session/state JSON）与 workspace 级事件流

## Discriminator
两项当时已知事实之一即可收窄：1) workspace 事件流已显示并发/排期会话数分钟前正在同一制品上执行发布流水线；2) 发布脚本自身按设计把每个阶段（含最终 submitted）追加写入共享 session JSON——台账 log 尾部有无 terminal 标记直接把『重跑整个流水线』缩成『读一个文件』

## Short path
- 无活动 goal 的极简指令 → event_stream(scope=workspace)：是否有并发/排期会话已在执行同名推送
- 在执行或可能已执行 → 直读共享阶段台账 JSON 的 log 尾部，找 terminal 标记及其时间戳、内容 sha
- 标记存在且内容身份匹配 → 放弃 prepare/confirm，关闭已备好的 tab，不把可见的确认按钮当执行义务
- 外部核验唯一性：作品/实例管理页同标题计数==1、公网 URL 已 live，然后转验证与报告
- 仅当台账无 terminal 标记且并发写者已被独立裁决为已死（参 owner-closeout 取守分叉）才接管执行

## Stop conditions
- 台账 terminal 标记存在，且外部管理页确认同标题/实例唯一 → 停止一切执行动作，转收口报告
- 公网已 live 且其内容身份与台账标记一致 → 停

## Verification
- 刷新外部管理页，目标同标题/实例计数==1
- 台账标记的时间戳与产物内容 sha（如粘贴 HTML 哈希）确实对应 live 版本，身份匹配而非仅标记存在

## Counterexamples
- 台账按会话隔离、无共享写入 → 台账无法裁决并发状态，须直接查外部系统唯一性
- 平台发布后可自助编辑（动作可回滚）→ 重复成本低，按多平台不可逆性排序法处理，不必前置拦截
- 台账 terminal 标记来自旧版本、内容 sha 与当前修订不匹配 → 视为『当前版未发布』，但也不据此点第二次发布，走编辑替换流程
- 确认自己唯一持有执行权且事件流无并发会话 → 直接执行，读台账仅为断点续跑而非防重
