---
method_id: bare-id-state-reconcile-before-transition-retry-588019de930e
name: bare-id-state-reconcile-before-transition-retry
description: 在重发或补登记任何状态迁移动作（complete/publish/register/restart）之前，先用裸唯一 ID 检索记录/状态面，并按时间戳取最新记录作为当前权威状态；旧的 executing/pending/unverified 行一旦被更新的记录（已列出该迁移工具的 episode 简报、终态字段）覆盖，即视为陈旧快照，应跳过重复迁移而不是再试一次。检索带全局唯一 ID 的实体时不要附加自由文本词。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:1709:4b7bd2eb9f852bf40ed6
evidence_refs: learning:learn:ab34838d4531
created_at: 2026-09-20T05:07:15.108273+00:00
updated_at: 2026-09-20T05:07:15.108273+00:00
---
## Trigger
需要决定是否重发/补登记一个先前已发起、结果存疑的状态迁移（登记完成、publish、重启、关闭），或需要对带唯一 ID 的实体（PR/EVO/action）做记录检索时

## Discriminator
裸 ID 检索命中的记录集中，时间戳最新的那条是否已包含该迁移动作（工具调用名/收口简报/终态字段）。若有，当前状态已是 executed/merged，旧的 executing unverified 行是过期快照；若无（或最新记录是失败 detail），才需要按归档诊断链重发。本判据只用检索当时已暴露的时间戳与工具名，不依赖守卫事后的拒绝回执。

## Short path
- 并行查各实体终态（PR state、service status），只解决'合并终态与服务漂移'这一个未知量
- 对失败/漂移项先读已归档诊断（experience 文件），获得诊断链与重发前置条件，而不是直接重试
- 对每个待迁移实体用裸唯一 ID（不加主题词）检索一次，按时间戳取最新记录判定权威状态；最新记录已含迁移动作则直接跳过登记
- 本地核验重发前置：分支=main、tracked-clean、HEAD==desired generation 绑定的 head
- 前置满足则带正确 generation/ID 重发一次迁移动作，按回执的两阶段等待协议立即结束本轮、不轮询
- 按回执指示注册续跑终态核验（status+action_id），如实现状态而不重复操作

## Stop conditions
- 最新时间戳记录已证明迁移完成（executed/merged/accepted）→ 不再重复登记或重发
- 重发已被受理且回执要求等待会话空闲 → 本轮立即结束，交给续跑轮查终态
- 重发前置不满足（本地 HEAD 与 desired 不一致、非 main 分支或 tracked-dirty）→ 停止模型侧重试，转入 operator 流程

## Verification
- 迁移动作未被守卫以'状态不符/重复登记'拒绝；若被拒，用回执给出的真实当前状态反查自己是否漏看了更新的记录
- 续跑终态核验时 live.git_head==desired head、restart_required=false、pid_alive 为新 pid
- 本次会话对每个实体只发起一次状态迁移动作，无被守卫拦截的重复尝试

## Counterexamples
- 最新记录显示该迁移此前以失败告终（含失败 action_id 与 detail）→ 必须按诊断链修复前置后重发，不能因'已存在记录'而跳过
- 记录系统是语义/向量检索而非子串匹配时，裸 ID 查询未必最优，附加描述词可能反而提高召回
- 全新实体无任何历史记录 → 直接执行迁移，无需状态调和
- 存在专用权威 status 端点（如带 action_id 的 service_control status）可直接给出当前终态时，应直查状态面，不要先做记录检索绕路
