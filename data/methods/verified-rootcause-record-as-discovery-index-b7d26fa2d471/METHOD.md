---
method_id: verified-rootcause-record-as-discovery-index-b7d26fa2d471
name: verified-rootcause-record-as-discovery-index
description: 当任务是核实某代码机制在当前仓库的实现事实（位置/常量/公式），且 records 检索已命中自己此前对该同一机制的 verified 根因经验记录（标题精确匹配、含修复链）时，第一个动作应是读该记录全文，把它内嵌的 symbol/file/错误码引用当作发现索引：逐个定点 grep 并在当前 HEAD 验证。而不是先做全仓关键字/文件名宽枚举（命中 tests/evals 噪声），也不对已知数量枚举字面量变体（196608 / 192*1024 / 192_1024）。记录是索引不是真值：所有引用以本会话回执为准，grep miss 即对该单项回落宽发现。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1b498f1a-b510-4497-be53-2ae3460c91be:359:09e02fcbc4bf844d0dae
evidence_refs: learning:learn:a9a5e35e2426
created_at: 2026-10-21T06:48:41.253868+08:00
updated_at: 2026-10-21T06:48:41.253868+08:00
---
## Trigger
任务要求核实某代码机制在当前仓库的实现事实，records 检索已命中自己此前针对同一机制的 verified 根因经验记录（record_kind=experience、标题直接命名该机制与修复链），但该记录全文尚未读取

## Discriminator
检索回执本身：record_kind=experience、verification_state=verified、卡龄新（本例 0d）、标题精确命名待核实机制（『审查材料超 reviewer 子代理 history 预算…修复链』）——此类根因记录通常内嵌精确 symbol/file 引用，足以把『在全仓库找两个机制』缩成『读一条记录+定点验证几处命名位置』

## Short path
- 列出待核实未知量清单（本例：材料上限定义处、reviewer 预算公式处）
- records 命中匹配的自身 verified 根因记录 → 立即读全文，抽取其引用的 symbol/file/错误码清单（如 runner._bounded_child_wire、factory._child_context_limits）
- 对每个命名 symbol 在实现目录（如 src/…）做定点 grep，确认当前 HEAD 仍存在并取行号
- read_file 命中行邻域 span，核对常量/公式/注释语义仍与记录一致
- 每条会进入产出的论断都有本会话 file:line 支撑后停止取证；仅对记录未覆盖的未知量才发起宽发现

## Stop conditions
- 所有将写入产出的机制论断均已由当前树的定点 read 回执支撑
- 记录未覆盖或 grep 无命中的未知量已单独回落宽发现并闭环

## Verification
- 产出的每个 file:line 引用与本会话最终 read 回执逐字一致
- 记录中的行号/数值未直接转抄：行号与常量均以本会话回执为准（防记录过期）
- 确认未对已命中记录覆盖的事实再做补充性宽检索或字面量变体猜测

## Counterexamples
- 检索只命中 scenario 级、无任何代码引用的记录 → 无索引价值，直接正常仓库发现
- 记录陈旧且仓库大重构后 symbol 已改名 → grep miss 即视为过期线索，回落宽发现，不得强行套用
- 任务要求独立审计、明确禁止依赖既往记录 → 不适用
- 待核实对象是运行时行为而非静态代码 → 记录只能提供假设，仍须实测验证
- 记录命中的机制与当前待核实机制仅主题相邻（如诊断 reviewer_unavailable 的分类问题 vs 核实材料上限常量）而符号不重叠 → 只取相关条目，不把整卡当索引
