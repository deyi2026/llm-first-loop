---
method_id: verify-presupposed-failure-via-live-metrics-and-record-scope-3ea547be8a84
name: verify-presupposed-failure-via-live-metrics-and-record-scope
description: 当任务或既有结论断言'某机制当前失效/异常'（缓存失效、命中率异常、回归）并要求查原因时，先做证据可采性检查再找原因：(1) live 快照中当前 scope 的核心指标与采样窗口计数；(2) 失败记录的 scope 键（provider/session/时间戳）是否与当前 run 一致；(3) 测量仪器的实际覆盖范围。scope 不匹配、单轮数据、0.0 出自空窗口（win_runs=0）、或推断超出仪器覆盖时，'当前失效'不成立，正确答案是'无当前故障'而非继续归因。定位为 root-cause 方法的前置门，不替代其实验设计。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:7bd90e8c-559a-47d4-8b0a-a458da824909:18:bacc8e29010ae55266c7
evidence_refs: learning:learn:ba6cc67f356d
created_at: 2026-09-28T17:45:44.483167+08:00
updated_at: 2026-09-28T17:45:44.483167+08:00
---
## Trigger
用户或上一轮结论预设'机制 X 当前失效'并要求查原因（如'查一下 prefix 缓存失效的原因'）；环境存在可读取的 live 运行时快照（含指标与窗口计数）和带 provider/session/时间戳等 scope 字段的历史 action/trace 记录。

## Discriminator
读完快照后即可用的三类当时事实：当前 provider 与 llm_rounds/命中率/prefix_changed 等核心指标；窗口计数（win_runs/hit_win_size）决定 0.0 是'未采样'还是真低值；失败记录的 provider/时间戳与测量模块 docstring 声明的覆盖范围（本集：指纹只含消息列表、不含 tools 数组）。本集实例：glm/8 天前记录 vs 当前 minimax、llm_rounds=1、hit_rate=0.949、'380 字符=38K tool schema 重传'超出仪器覆盖——'当前缓存失效'不成立。

## Short path
- 读 live 快照并取全（截断则按 range 续读），提取核心指标与窗口计数。未知量：当前 scope 是否真的存在失效。
- 读测量/指标定义源码：确认仪器覆盖范围，并从 record_action 调用处取得确切事件名（run.prefix_stability）。未知量：指标到底测什么、去哪检索原始记录。
- 用事件名（而非字段值拼接）检索历史记录，摘出每条的 provider/session/时间戳并与快照对比。未知量：被引用记录说的是否当前 run（本集首查按字段值检索即 miss，按事件名即命中）。
- 对同类 verdict 区分不同形态（本集：head=0 型=历史截断 vs working_set 型=真改写源；attribution 字段已退化无归因价值）；仅当 live 指标在非空窗口、≥2 轮数据下确实异常才进入阶段归因。
- 直接从 config 定义源码枚举全部相关开关作答，不凭记忆（本集：仅 3 个 cache 相关设置，无通用 provider 缓存开关；anthropic_cache_control 仅 localhost 生效）。

## Stop conditions
- 当前 scope 的 live 指标健康（非空窗口、命中率正常、prefix_changed=false）→ 直接回答'当前无失效'，停止找原因。
- 所有支撑'失效'的记录 scope 不匹配或过期 → 结论为'历史现象/跨 provider 混淆'，停止归因。
- 指标为 0.0 但窗口计数为 0 → 记为'未采样'，不得作为故障证据。
- 切 provider/session 属合法缓存清空事件（tracker 以 (session, provider) 为键）→ cold_baseline 是预期行为，不是故障。

## Verification
- 结论必须引用 live 快照数值+获取时间戳；每条被驳回的历史记录引用其 provider/时间戳原文。
- 开关枚举与行号必须来自 config 定义源码，不来自记忆（本集末段专门补了这步）。
- 回答显式列出未核验项（本集：compressed 标记来源、glm 时代 380 字符 system 改写原因），不伪装成已验证。

## Counterexamples
- live 快照本身异常：非空窗口下命中率低、prefix_changed 连续多轮为 true → 本方法不适用，直接用 root-cause 方法做阶段归因与单变量实验。
- 失败记录与当前 run 同 scope（同 provider/session、时间近）→ 记录可采信，应继续查原因而非驳回。
- 无任何 live 遥测可读、只能依赖历史记录 → 本方法判别器不可用，应重跑测量，不得下'无故障'结论。
- 窗口计数非 0 且仪器语义已确认 → 0.0 是真实低值，不得套用'空窗口'解释。
