---
method_id: attribute-artifact-via-unique-token-before-impl-deep-read-28d50e49311f
name: attribute-artifact-via-unique-token-before-impl-deep-read
description: 面对来源不明的观测 artifact（日志行/审计记录），且任务结论依赖其写入者归属时，先用行内全局唯一 token 做跨线归因（git log --all -S / 跨 worktree 精确 grep），再决定读哪份实现。artifact 自带的测试特征（占位工具名、单 pid 毫秒级突发）可先行降级其“生产信号”地位。多部署线仓库中，未归因就深读某一条线的实现，容易把 A 线数据套在 B 线代码上，发现 token 缺失后才返工归因。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:493:506ce5c999732103a4e2
evidence_refs: learning:learn:70d1ece87fae
created_at: 2026-09-17T15:23:16.114120+00:00
updated_at: 2026-09-17T15:23:16.114120+00:00
---
## Trigger
拿到一条或一组观测 artifact（如审计 ledger、事件日志），其写入代码线未确定，且任务问题（该数据是否代表生产行为、对应机制是否影响目标指标）依赖写入者归因；仓库存在多条部署线/worktree；artifact 内含罕见字面 token。

## Discriminator
第一跳工具结果中已可见：ledger 行含全局唯一 kind 名（receipt_pointer）、占位工具名 "xyz"、全部 7 条来自单 pid 的毫秒级突发；同时已给出当前部署 worktree 标识，且仓库存在 .worktrees 多线。这些当时已知事实足以先用唯一 token 一次 pickaxe 定位写入 commit，并预判数据为测试写入，而不必先深读主线实现再事后发现 token 缺失。

## Short path
- 读 artifact 本体，提取唯一 token 与元数据（pid/ts/工具名/来源标签）；未知量：这是谁写的、代表生产还是测试？
- 用唯一 token 做全历史/全 worktree 归因（git log --all -S <token> 或跨 worktree 精确 grep）；未知量：写入 commit 与所在线。
- 对比写入线与当前部署标识；若不在运行线，则 artifact 降级为“候选线功能存在性证据”，与生产行为解耦，不再用其推断生产。
- 对真正运行线只核验会到达 wire 的注入路径：落点（前缀区/尾部追加）、确定性（一次冻结/每轮重渲染）、默认开关态。
- 取运行时指标验证时，先按会话 id 列目录定位日志文件（不猜扩展名，滚动分段目录是常见形态），构造层+实测层双确认即停。

## Stop conditions
- artifact 已归因到具体 commit/线，且其与当前生产部署的关系（在/不在运行线）已明确判定
- 运行线实际注入面的 wire 影响（位置/确定性/默认态）已由源码确认，并有运行时锚点指标（如前缀指纹不变率）佐证

## Verification
- 归因 commit 所在 worktree 与当前部署 worktree 不一致时，记录两者部署标识差异作为解耦证据
- 实测指标窗口覆盖含注入/失败事件的轮次，且前缀指纹等锚点指标在窗口内保持不变

## Counterexamples
- 仓库只有一条部署线且唯一 token 一击即中实现：归因平凡，直接读实现挂点即可，全历史 pickaxe 是多余开销
- 任务只问 artifact 的语义（这行记录是什么意思）而不问写入者或生产影响：读 schema/注释即可，无需作者归因
- token 是常见词（如 error/cache）不具备唯一性：git log -S 机制失效，需组合更长唯一串或改用结构化字段（pid、路径、事件名组合）归因
