---
method_id: non-attributable-structural-gate-red-escalate-costed-options-not-self-by-cb46e874451a
name: non-attributable-structural-gate-red-escalate-costed-options-not-self-bypass
description: fail-closed 门禁真实红（exit≠0、红数对账阻断）且红点不在本候选 changed 文件清单内、失败文本自述为环境结构性机制（如嵌套沙箱子进程 exit71/EPERM）或与既有同因记录吻合时，补救空间不在代理侧：登记 known-red=改 tracked 台账→树摘要变→已签发 tree-scope 资格失效→全链重跑；用 CI 绿/子代理正文替代本地门禁签发=证据替换裁决。这些均越 lane/护栏边界，不得自执行。正确动作：用门禁回执自身的 changed-file ratchet 清单机械核对归因、逐字绑定既有同因证据、把已核事实+未消费项（push 未发、资格未用）连同 evidence ref 写入台账，然后呈交带代价的裁决选项并停在授权边界，受闸动作（push/资格消费）全部冻结。
aliases: 门禁红在别的PR带来的测试上, 结构性失败要不要自己绕过, 登记known-red算不算越权, 嵌套沙箱下必挂的测试, 改树导致已签发资格失效, fail-closed阻断何时升级用户
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:d901b48e-25bf-45f0-a33f-23eaa879ddc3:721:317250aebeb2a1d94d8b
evidence_refs: learning:learn:c481c360f583
created_at: 2026-11-19T08:45:49.755329+08:00
updated_at: 2026-11-19T08:45:49.755329+08:00
---
## Trigger
fail-closed 门禁返回非零/阻断；失败测试路径不在本次候选的 changed 文件清单内；失败归因指向执行环境结构性限制（沙箱嵌套、setuid 拒绝等）而非候选代码回归

## Discriminator
同一门禁回执自带的 changed[committed] 文件清单与失败测试路径零交集（归因错配）；失败消息命名的是环境机制（sandbox child exited 71 / EPERM / probe NO-GO）而非候选代码断言差异；上下文中已存在可逐字绑定的同因历史记录（如嵌套沙箱不可执行的 help_request）

## Short path
- exit≠0 后只读门禁输出尾部一次，提取三样：失败测试 id+路径、失败类别/消息、changed-file 清单
- 机械比对失败路径 vs changed 清单得出归因判定（不在清单内=非我方回归）
- 归因非我方且成因结构性 → 绑定既有同因证据原文；不重跑全量、不代修他人 lane 的测试
- 逐项计算补救选项的机械后果并标注代价：known-red=tracked 变更→树内容摘要变→tree-scope 已签发资格失效→全链重跑；CI 绿替代=证据替换需用户拍板
- 写台账（已核事实+未执行项+evidence ref），呈交裁决选项，停在授权边界

## Stop conditions
- 用户裁决返回，按所选选项执行
- 归因核对显示失败测试在 changed 清单内 → 转正常修复候选路径，本方法停止适用
- 失败属 flaky（重跑绿）或红已登记 → 在常规授权内处理
- 已授权的无外层沙箱执行通道可用 → 在该通道取得真实门禁结果并消费

## Verification
- 失败测试路径与同一回执 changed 清单逐项比对，确认零交集
- 失败消息指向环境机制而非候选代码断言差异
- 同因历史证据以原文引用并写入台账 evidence ref
- 各选项代价由回执 scope 字段（如 consumable_scope.revalidated_on_use=整树内容摘要）推导，非臆测

## Counterexamples
- 失败测试属于本次 changed 文件清单 → 候选自身回归，直接修复重跑，不升级不越界
- 闸终判 REVISE 但同一回执内容计数 PASS → 属闸判定侧/合同缺陷，走窄复审或逐层归因卡，不走本卡
- 登记 known-red 属任务章程明确授权的动作 → 直接登记并重链，无需升级裁决
- 失败 flaky（每次不同测试红、重跑即绿）→ 有界重试，不构造裁决选项
