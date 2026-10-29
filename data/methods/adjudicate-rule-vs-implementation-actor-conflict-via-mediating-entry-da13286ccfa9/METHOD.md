---
method_id: adjudicate-rule-vs-implementation-actor-conflict-via-mediating-entry-da13286ccfa9
name: adjudicate-rule-vs-implementation-actor-conflict-via-mediating-entry
description: 当规则/义务层文本与实现/资格层文本对同一动作的执行者给出看似冲突的指派（『X 必须主动组织』 vs 『只有 Host 发起才有效』），不要直接报『方向相反』或归咎某侧文档走偏。先从更严格一侧已点名的中间入口（工具/API 名）入手，查清其调用者与实际执行者：若调用者=X、执行者满足严格约束，则两句相容，残差定性为中间文档缺一句桥接；用能力标志全仓唯一赋值点+通用派发面 schema 缺参佐证。仅当无中间入口或两侧无法同时满足时才定性真实分歧。
aliases: 规则和skill说的不一样听谁的, 义务层实现层打架先找中间工具, 谁调用谁执行搞清再定性冲突, 文档方向相反可能是缺桥接句, 先找调停入口再报矛盾, 父agent组织还是Host发起
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:3e24aff2-8af5-497f-882a-a249bcc66acd:474:d63b16fa398d29a9ba65
evidence_refs: learning:learn:d9ff1c414731
created_at: 2026-10-29T10:49:17.753292+08:00
updated_at: 2026-10-29T10:49:17.753292+08:00
---
## Trigger
同一系统内两份权威文本对同一义务的执行者指派不一致——义务/规则层写『X 必须主动组织某动作』，实现/资格层写『只有机制 M（如 Host）发起且不可受 X 干预才有效』——且正要据此报告矛盾、缺口或『方向相反』

## Discriminator
更严格一侧的冲突文本本身已点名中间入口（如同一段里写了工具名 review_admission(start/status)）：这提示存在一个工具面，其调用者可以是 X 而其内部执行者满足 M 的约束。该事实在宣布冲突之前就已可见，足以把『真分歧』假设降级为『缺桥接句』假设并先用一次定向 grep 验证

## Short path
- 并排引用两句冲突陈述及出处（义务层 vs 实现/资格层），暂不下『相反/缺口』结论
- 从更严格一侧的陈述里提取已点名的中间入口名，定位其定义处，回答两个未知量：入口的调用者是谁、被约束动作的实际执行者是谁
- 若调用者=X 且执行者满足 M 约束（父 agent 调 review_admission、Host 内部执行 start），两句相容——把残差定性为中间层文档缺桥接句，并写出那句桥接
- 佐证唯一性：能力标志只在中间入口内部路径赋值（全仓唯一赋值点），通用 spawn 面 schema 无此参数，资格 child 的后续通道限制也一致
- 仅当不存在中间入口、或调用者/执行者无法同时满足两侧陈述时，才报告真实分歧

## Stop conditions
- 调用者/执行者已同时满足两侧陈述：停止冲突定性，改报『中间文档缺桥接句』并附唯一赋值点与 schema 缺参证据
- 缺口层级定性（误导性文档 vs 机制漏洞）与一句话修法已给出，不再继续枚举实现文件

## Verification
- 复检能力标志（如 review_isolated=True）全仓唯一赋值点确在中间入口的内部执行路径
- 确认通用派发面（spawn schema/公开参数）确实不含该标志，按旧字面路径执行只会拿到无资格回执且拦截提示自解释正确入口

## Counterexamples
- 两层文本规定的行为真互斥且无任何工具面居间（如规则要求审查者可跑测试、运行时硬拒审查者一切工具）：这是真实分歧，直接报告冲突，不要硬找调停入口
- 点名的中间入口已废弃或未接线（死工具）：错的是义务层文本，修正方向反转
- 只是单层文档漏写步骤、没有第二层说法参与冲突：直接补步骤即可，无需跨层裁决
