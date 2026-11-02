---
method_id: verify-capability-in-weights-index-not-config-declaration-55291fc09e17
name: verify-capability-in-weights-index-not-config-declaration
description: 审查依赖『某实体具备能力X』的行动建议时，别只核建议明说的断言：先反推载荷假设，测量对象是否真需要X在场——再到X物理所在层（权重索引/实体工件）裁决，而非 config/README/同家族类比层。转换、量化、fork 管线惯常原样搬运声明却剥离实体（本集：MLX 转换版 config 声明 mtp 层数=1，733 个权重键中 mtp.* 为零），于是按 config 选定的实验测不到声称机制，同批加速比的机制归因一并失效。零命中时改道：换确有权重的 checkpoint 或重标实验目的，并回扫所有依赖X的结论。
aliases: config 声明了但权重里没有怎么查, 量化转换会不会把 MTP 头剥掉, 确认 checkpoint 带不带某能力, 实验机制前提先证伪再设计, safetensors 索引查能力参数键
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:40d20564-ac46-4792-b62c-f0b083523714:0:407ea7356ab6b893b0df
evidence_refs: learning:learn:e96509245be4
created_at: 2026-11-01T20:19:35.744444+08:00
updated_at: 2026-11-01T20:19:35.744444+08:00
---
## Trigger
一份分析/实验方案的动作建议，其测量对象依赖某本地模型或转换/量化产物具备特定能力（native MTP 头、vision tower、adapter 权重等），而该能力仅由 config 声明、README、同架构家族类比或上游默认支撑，未经实体层核验

## Discriminator
声明层与实体层可以分叉：转换/量化/fork 管线通常原样搬运 config 却剥掉辅助参数，config 写能力开=1 与权重索引中能力键为零可以并存（本集 733 键零命中）。读一次权重索引/weight map 并检索能力对应键前缀，即可把『应该有』裁成『有/没有』，一次读取终结争论

## Short path
- 从建议反推载荷未知量：其测量对象（如『不依赖外部 draft 的 native MTP 路径』）需要哪个能力物理在场，把裁决这一事实排在核验建议明说的断言之前
- 到能力物理所在层取证：读权重索引/weight map，检索该能力的参数键前缀；零命中即证伪 config/类比层假设，且对照同家族原始发布版区分『转换剥离』与『本来就没有』
- 证伪后改道而非修补：换用确有能力实体的 checkpoint，或把实验重标为『server 实现对比、该能力关闭』，不按原目的执行
- 回扫同批结论中依赖同一能力假设的归因（如加速比机制归因），逐条降级为『机制未证实』
- 其余陈述性断言照常低成本核验，但不再作为『方案成立』的证据累积

## Stop conditions
- 权重索引对能力键给出明确的有/无裁决，且依赖该能力的全部结论已回扫完毕
- 能力为纯声明驱动、无独立实体参数（此时声明层即权威层，实体检索无意义）

## Verification
- 命中的能力键确实落在非空分片（非悬空引用/空文件）
- 同家族原始发布版对照坐实『转换剥离』而非『上游本就无此能力』
- 若实验仍要跑，把『按 config 实例化该能力路径的加载行为』（硬失败还是静默降级）列为首个 smoke 项，而非实验项

## Counterexamples
- 能力无独立参数、纯 config 驱动（rope scaling、sliding window 等）：config 即实体层，做权重键检索只会误判
- 实验目的与该能力无关（整体可用性/吞吐冒烟对比）：能力缺失只改实验标签与解释，不应据此否决整个方案
- 实体不在本地、发布方文档/注册表为权威出处：先走发布渠道核验存在性与版本，本地实体检查仅在文件在手时有意义
