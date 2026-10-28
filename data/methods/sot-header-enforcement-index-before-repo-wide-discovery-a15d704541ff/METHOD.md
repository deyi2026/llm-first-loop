---
method_id: sot-header-enforcement-index-before-repo-wide-discovery-a15d704541ff
name: sot-header-enforcement-index-before-repo-wide-discovery
description: 为治理 SoT 规则定位 enforcement 落点（注入清单、declaration 管线、代码锚点）或设计新落点时，先消费 SoT 头部自声明的一致性架构：它点名 enforcement 工件（同步测试文件名、prompt 边界符号）并声明禁止性落位（如『规则正文不进 universal prompt』）——前者是符号级窄 grep 索引，后者可直接淘汰候选落点。全仓内容搜索会被生成物目录（evals/build）淹没并超时；先用一次有界 ls 确定真实代码根，把文档路径简写映射到实际目录树后再 grep。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:1118:3712aa542000c047981e
evidence_refs: learning:learn:5d6f10766a3d
created_at: 2026-10-21T18:51:30.404446+08:00
updated_at: 2026-10-21T18:51:30.404446+08:00
---
## Trigger
任务要求 (a) 核实某规则相关的注入清单/声明管线/enforcement 管线的实际位置，或 (b) 为规则义务设计代码级落点（演进建议），且规则 SoT 头部自声明了一致性维护/边界架构（点名同步测试、点名符号、『不是/不进 XX』式声明）

## Discriminator
已读的 SoT 头部显式点名 enforcement 工件与边界符号（同步测试文件名、SYSTEM_PROMPT_EXTRA/build_system_prompt 类符号）及禁止落位声明——这些符号与边界事实在第一份读取回执中即已存在，足以把『全仓找管线』缩成『几次符号限定 grep + 一次有界代码根确认』，并足以提前淘汰违反声明边界的候选落点

## Short path
- 读 SoT 头部，提取点名的 enforcement 工件（同步测试、prompt 符号）与禁止落位声明；未知量：enforcement 面在哪、哪些落点已被排除
- SoT 文件内 grep 规则编号定位正文行号并读全文；未知量：规则语义（审阅/建议的输入）
- 一次有界 ls/find（深度≤2、排除生成物目录）确定真实代码根，把文档路径简写映射到实际树（如 core/prompt.py → src/llm_loop/...）；未知量：该在哪 grep
- 代码根内符号限定 grep：既有规则锚点全貌（已验证模式）、目标规则零命中核验、头部点名的管线符号；未知量：既有落点模式与管线真实位置
- 候选落点按头部声明边界过滤、对齐既有规则已验证的锚点模式后转入撰写；全部事实以回执闭环即停

## Stop conditions
- 既有规则锚点、目标规则零命中状态、管线真实位置、边界约束四类事实均有 file:line 回执闭环，立即转入建议撰写
- 头部声明被活树回执证伪（如同步测试不存在）→ 把矛盾本身记为发现并转入修订建议，不再枚举其余落点
- 候选落点全部被声明边界淘汰、或全部落入声明边界内 → 转入核验与提交

## Verification
- 每个落点定位到 file:line，且与 SoT 头部声明一致（同步测试存在、断言方向与头部描述吻合）
- 目标规则零命中用限定在代码根+tests 的 grep 复核（排除 evals/build 与二进制 pyc）
- 最终建议不触碰头部显式禁止的落位；『某落点被边界声明排除』以回执为据而非推断

## Counterexamples
- SoT 头部无自声明一致性架构或命名符号 → 头部不提供 provenance 边，有界目录发现是合法首步
- 任务前提就是审计『头部声明的边界是否真实被执行』（怀疑同步测试过期/被删）→ 声明不能当事实，必须读测试与 CI 回执验证
- 规则正文分散多文件而非单一 SoT → 单文件定位不成立，需耦合面枚举
- 小型干净仓库无生成物目录 → 全仓搜索成本低，本方法的排除纪律无增益
