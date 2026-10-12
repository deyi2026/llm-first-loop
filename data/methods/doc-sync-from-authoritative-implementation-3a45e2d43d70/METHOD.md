---
method_id: doc-sync-from-authoritative-implementation-3a45e2d43d70
name: doc-sync-from-authoritative-implementation
description: 把新服务/通道/target 补进运维 skill 或操作文档前，先在权威实现（脚本/代码）里核实三元组：主调度 case 接受的 target 名、启动函数的就绪探针（端口/心跳文件/manifest pid 三类之一）、门禁与时序差异；文件内 usage 注释与实现工件冲突时以实现为准（注释过期 ≠ 能力缺失）；随后同步更新该能力涉及的所有文档面——命令清单、验证清单、frontmatter description、内部计数——再提交，避免只改一处造成文档面之间互相矛盾。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:2294:9f36ee25fb13aea08a4a
evidence_refs: learning:learn:1295250ea69b
created_at: 2026-09-24T04:39:15.681168+00:00
updated_at: 2026-09-24T04:39:15.681168+00:00
---
## Trigger
用户要求把某服务/通道/能力补进现有 skill 或操作文档，且该文档断言的行为由某个脚本/代码实现承载，而文档（或实现内注释）可能已落后于实现

## Discriminator
grep 通道名同时命中实现工件（主调度 case 标签含该通道、存在对应的 _pids/_stop/_start 函数）但 usage/文档注释未列出该通道——此时候选结论锁定为'能力已支持、注释过期'，下一步只需读启动/验证函数提取就绪探针，不修改实现、也不重查无关分支；若只命中注释而无实现命中，则能力缺失，先改实现或向用户澄清，不得把期望写成现状

## Short path
- 在权威实现中 grep 通道名；未知量：能力是否已存在、入口在哪
- 读主调度 case 与该通道的启动/验证函数；未知量：确切 target 名、就绪探针类型、门禁差异
- 通读目标 skill 的全部相关面（命令清单、验证清单、frontmatter description）；未知量：哪些面需要加行/改计数
- 逐面原子编辑并复读 diff；未知量：表述是否与实现逐字一致、未删既有正确内容
- 同步文档内部计数与描述（如验证步数、服务范围），提交并按通道回报探针三元组

## Stop conditions
- 每个新增通道的 target 名 + 就绪探针 + 门禁差异三元组均已从实现核实
- 两处以上文档面（含 description）已一致反映新通道，grep 无残留旧计数或旧 target 范围
- diff 复读一致且变更已提交

## Verification
- 文档中的命令与探针逐字对照实现：case 标签名、探针文件路径与字段名、就绪等待窗口
- grep 文档确认无残留旧表述（旧验证步数、未含新通道的 target 列表）
- 编辑回执显示新增行未覆盖既有正确内容

## Counterexamples
- 纯措辞/排版类文档修改——无需查实现，直接编辑即可，查实现纯属浪费调用
- 行为权威不在被查脚本（target 词表由远程服务注册表或另一入口定义）——只 grep 本地脚本会得出错误词表
- 通道在实现中不存在（无 case 标签、无函数命中）——此时应先改实现或向用户澄清，而不是先写文档
- 全新独立文档（无既有面需要保持一致）——只需实现核实一步，无多面同步需求
