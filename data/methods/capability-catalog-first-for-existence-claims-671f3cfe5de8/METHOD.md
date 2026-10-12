---
method_id: capability-catalog-first-for-existence-claims-671f3cfe5de8
name: capability-catalog-first-for-existence-claims
description: 当需要证实/证伪『系统是否支持某机制、通道或权限，由谁把守』这类存在性/归属断言时，先定位系统自己维护的枚举式能力目录（工具 registry、能力矩阵、config schema、API 索引），一次读取穷举候选集合并按名称/描述缩到 1-2 个命名实现，再只对这些候选做定义面精读。不要先对实现文件与相邻子系统做关键词扫荡：usage 扫描枚举的是『用在哪里』，回答不了『有什么』。本集 registry.py 一行描述即同时给出通道存在、直接-parent 门与预算，可避免 handoff/fleet/runner 内部的宽扫和 2400 行大文件精读。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:9bd2b826-af96-4acb-87be-49c2646f1725:86:02108aafce8bb72cf492
evidence_refs: learning:learn:4694e623b5dd
created_at: 2026-10-11T08:11:27.641488+08:00
updated_at: 2026-10-11T08:11:27.641488+08:00
---
## Trigger
需核实存在性/归属断言：某机制、通道或权限『是否存在、在哪里实现、由谁把守』——常见于用户纠正与先前结论冲突、或两种架构判断相持需回代码裁决时；且代码库中存在 registry/schema/矩阵类可枚举目录。

## Discriminator
进入宽扫之前已可见：(a) session_continuity 检索命中自带官方标签『terminal 后有界续话窗口』（execution_surface.py:127、introspection/tools_model.py:205），与用户断言『卡顿后接管续话』语义一一对应，把候选空间从整个 runtime 缩到『实现续话的那个工具』；(b) registry.py:110 的 name→一句话描述形态表明该文件是内置工具的权威目录，一次读取即可穷举全部 agent 间通道（agent_message/agent_followup/subagent_result）及其门与预算。两条均为当时已知事实，满足 knowledge-at-time。

## Short path
- 一次定向检索（session_continuity）确认能力矩阵与官方标签『有界续话』，并从命中形态识别 registry.py 为工具目录（本集第 2 步即已具备）
- 用目录语言（续话/followup）再做一次定向检索，命中 registry.py:128/131 与 agent_followup.py——通道存在性、预算（每 child≤2/父≤4/15min）、门=『已终止的直接 child』一次到位
- 只精读命名候选的定义面（agent_followup.py、agent_message.py、spawn_subagent 的 requires schema），提取门类型：是否直接 parent/child 的拓扑位置门，而非角色白名单
- 一次定向检索核 MAX_DEPTH 与 direct-parent 检查的代码行（runner.py），验证用户方案（监督者插在工人上层）落在深度上限 3 内
- 每个断言成分都有定义面/registry 行出处即停，输出更正；不进入 handoff/hotcard/fleet 等相邻子系统扫荡，不精读 2400 行 runner.py 全文

## Stop conditions
- 用户断言的每个成分（存在性、门/授权位置、预算与深度约束）均已取得 registry 或定义文件行号出处且相互一致
- 目录已把候选缩到 1-2 个命名实现，继续宽度检索不会新增决定性事实

## Verification
- 结论中每个关键句可指回 registry 行/定义面行号（如 registry.py:128/131、execution_surface.py:127、agent_followup.py:11）
- 目录描述与定义面代码一致（requires schema、gate 条件、预算常量），无『目录说有、代码说无』的矛盾
- 若要下『机制不存在』的结论，必须至少核过一次接线/调用点，不能仅凭目录缺席

## Counterexamples
- 目录缺失、过期或未登记实验特性时不应盲信目录：本集代码自述 handoff 曾生成空壳（hotcard.py:3 背景①），目录/文档与实现可能脱节，须先核接线再下结论
- 问题问的是运行时行为而非存在性（预算是否真被强制、门是否真拦截）时，目录只证明『声明了』不证明『执行了』，需 callsite 或运行验证
- 目标是掌握某个具体调用的契约（签名/返回结构/完整调用点）时，应走 method-repo-api-discovery 的定义面+调用点路径，目录枚举不解决该问题
