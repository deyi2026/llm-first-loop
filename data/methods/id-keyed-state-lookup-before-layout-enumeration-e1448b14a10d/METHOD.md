---
method_id: id-keyed-state-lookup-before-layout-enumeration-e1448b14a10d
name: id-keyed-state-lookup-before-layout-enumeration
description: 当待核查对象已带有唯一字面标识（动作/部署/回执 ID）且环境提供文件名+内容搜索原语时，应以该标识为键直接定位权威状态记录，而非枚举目录结构或猜测存储路径。本集为核对两个 svc-* 动作终态，连续 ls data/、猜错 data/state/ 与源码布局多次，才在 data/runtime/service-control-actions/ 找到真值；而动作 ID 早在交接消息中给出，一次内容搜索即可直达。适用于任何『已有精确 ID + 可搜索状态存储』的控制面/运维核查场景。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:966:b519d87c58da7e351e63
evidence_refs: learning:learn:17236f8578cb
created_at: 2026-09-18T19:14:08.487965+00:00
updated_at: 2026-09-18T19:14:08.487965+00:00
---
## Trigger
需要获取某条已被命名记录（携带唯一 ID）的权威状态/终态，但其存储位置未知；环境中存在可用的文件名+内容搜索工具

## Discriminator
知识时点事实：交接消息已明确给出目标记录的唯一标识（如 svc-7cd6ffaf…），且本轮第 2 步已实际验证 search_files 内容搜索可用、首个权威结果（deployment 记录）已给出 runtime_root/data 锚点——这三者当时就足以把『整个 data/ 目录树』缩成『一次按键定位』

## Short path
- 1. 先调控制面 status/部署记录查询，确认 desired 代与 runtime_root 锚点（未知量：当前期望状态）
- 2. 若 status 未含目标记录，用手中唯一 ID 做文件名+内容搜索，直达其状态 JSON（未知量：该动作终态）
- 3. 读取命中记录的 status/detail 字段（未知量：是否终态、失败根因线索）
- 4. 必要时按记录内 receipt/日志线索做一次定向 tail（未知量：失败的具体预检原因）
- 5. 根因足以改变决策（如：不向 worktree 发布的 desired 发 restart，移交 operator 从正仓 publish）即停止发现

## Stop conditions
- 目标记录的终态与 detail 已从权威存储读到，且与 desired 记录互相印证
- 证据已足以决定下一步控制动作发或不发
- 触发权限边界（operator-only）时停止尝试并转为交接说明

## Verification
- 命中文件位于首个权威结果给出的 runtime_root/data 之下，路径与 schema 命名一致
- 记录内 deployment_id/generation 与 desired deployment 记录一致
- 失败 detail 与 worker 日志/回执内容相互一致（如 restart_mirror rc=1 与预检隔离日志对应）

## Counterexamples
- 无唯一 ID 的聚合查询（如『最近所有失败动作』）——应使用列表/status API 或约定目录，ID 键搜索不适用
- 状态存于数据库或远端服务、内容搜索不可见——应走控制面自带查询而非文件系统
- 标识不唯一或噪声大（如 generation 42 出现在数百文件中）——改按 schema 名或专用 status 工具定位
