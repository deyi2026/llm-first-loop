---
method_id: truncation-aware-failure-targeted-log-fetch-8556cb79f297
name: truncation-aware-failure-targeted-log-fetch
description: 长日志（如 CI job log）的观测窗口被截断时（回执标 complete:false/next_start，或所示行时间戳全部早于 job 已知结束时间），不要重复同一条全量读取命令碰运气；改用失败定向提取（--log-failed，或对 error/fail/exit code 做 grep），每个失败 job 一次取到失败行；再由失败行命中的具体条件去 gate 脚本/配置中 grep 确认触发语义，随后停止读日志、转入修复。核心判断：截断元数据证明『失败行在窗口之外』，此时重跑同一宽命令是不可靠的枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:799:1758d3811e58433620d3
evidence_refs: learning:learn:c89ccef7e75a
created_at: 2026-09-18T01:24:35.484483+00:00
updated_at: 2026-09-18T01:24:35.484483+00:00
---
## Trigger
需要从 CI/长日志定位失败原因，且首次读取返回的是被截断的前缀窗口（多为 setup 步骤行），而 check 列表已提供 failing job 的 id、时长或结束时间

## Discriminator
当时即可见的截断证据：工具回执带 complete:false 与 next_start（显式分页续点），或展示行时间戳全部早于该 job 已知结束时间——任一成立即证明失败行在当前窗口之外，同参数重跑不会稳定补齐

## Short path
- 用 check 列举（如 gh pr checks）拿失败 job 的 id/URL；未知量：哪些 check 失败
- 对每个失败 job 做一次失败定向读取（--log-failed，或 --log | grep -iE 'error|fail|exit code' -A2）；未知量：失败原因行
- 失败行命中的具体条件（如『期望恰好 1 个 X，实际 0』）→ 在 gate 脚本/配置中 grep 该条件，确认触发语义；未知量：何时触发
- 每个失败 check 归因到一条具体条件即停止读日志，转入修复或本地复现；不再重读全量日志

## Stop conditions
- 每个失败 check 已有一句具体失败行 + 可在源码/配置中定位的触发条件
- 确认失败信息不在 step 日志层（在 check annotations/PR summary）时，改查对应层级并停止 grep 日志

## Verification
- 提取到的失败行时间戳接近 job 结束时间，而非 setup 段
- 失败行中的条件能在 gate 脚本/工作流配置里找到对应实现（非噪音行）
- 按该条件修复或本地复现后，对应 check 转绿

## Counterexamples
- 日志窗口已完整且包含失败行：直接分析即可，无需任何定向提取
- 失败原因在 check annotations/PR summary 而非 step 日志：grep 日志是错误层级，应先查注解
- 工具既无失败过滤标志也无分页元数据：退化为按 next_start/tail 做一次有界续读；重复同一全量命令仍属反模式
