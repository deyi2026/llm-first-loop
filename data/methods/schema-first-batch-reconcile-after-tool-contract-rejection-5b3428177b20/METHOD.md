---
method_id: schema-first-batch-reconcile-after-tool-contract-rejection-5b3428177b20
name: schema-first-batch-reconcile-after-tool-contract-rejection
description: 当工具以参数契约错误拒绝调用且回执点名权威 schema 入口（如 get_tool_schema）并要求一次性修正全部字段时：在下次调用同一工具前先读取一次完整 schema，并按它核对本次及所有已计划的同工具后续调用（同一多-action 工具的不同 action 常有不同必填字段），一次性补齐；不要每次只补回执点名的单个缺失字段。适用于同一工具将被连续多次调用的场景，把 N 次同类失败压缩为 1 次 schema 读取。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8098b445-b87e-4252-a938-91924f37f4db:237:63ae6408d45922a42ee6
evidence_refs: learning:learn:d6b9382a3edc
created_at: 2026-10-07T11:41:57.832989+08:00
updated_at: 2026-10-07T11:41:57.832989+08:00
---
## Trigger
工具调用被参数契约错误拒绝（回执含 missing=… 或等价必填字段缺失信息），且回执显式给出契约/spec 读取入口，同时已知随后还要以不同 action/参数再次调用同一工具（如 publish 后跟多个 restart）。

## Discriminator
拒绝回执当时已自带两条事实：① 它点名补救入口（get_tool_schema(service_control)）并要求『一次性修正全部字段』；② 前一成功回执的 next 字段已模板化后续调用签名（action=restart, target=…, expected_generation=…）。两条在场却仍逐次单字段修补，是可避免失败的确定性信号（knowledge-at-time 成立，未用后见信息）。

## Short path
- 首次契约拒绝后：先读回执点名的 schema 入口一次（get_tool_schema(工具名)），而非直接重发修补版调用
- 按 schema 枚举本工具全部计划调用（publish + 各 restart）的必填字段，一次对齐全部差异
- 以完整字段重发被拒调用；成功后按 schema 直接发起后续各 action，不再等回执逐次点名
- 直至切换到其他工具/调用集合变化，才需要重新核对 schema

## Stop conditions
- 全部计划的同工具调用均以完整契约通过（accepted/success 回执）
- schema 入口不存在或读取失败：退回按回执逐字段修正
- 计划中的调用集合发生变化：重新核对相应 action 的 schema

## Verification
- 每次重发/后续调用前，将实际参数与 schema 必填字段清单逐一对照
- 后续回执不再出现 missing=/参数契约类拒绝（本集可省去 restart 缺 target 的那 1 次失败）

## Counterexamples
- 单次调用且回执已完整枚举全部缺失字段：直接按回执修正即可，读 schema 徒增一轮
- 拒绝原因非契约（权限、瞬态超时、404、任务不存在）：schema 无法解决，按对应故障类别处理
- schema 缺失或与回执矛盾（get_tool_schema 无该工具/字段对不上）：回执驱动修正优先
- 失败字段是 schema 未覆盖的运行时语义约束：读 schema 得不到该信息，需其他证据源
