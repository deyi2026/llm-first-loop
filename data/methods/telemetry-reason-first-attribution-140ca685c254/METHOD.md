---
method_id: telemetry-reason-first-attribution-140ca685c254
name: telemetry-reason-first-attribution
description: 当结构化遥测（journal/事件流）带显式失败 reason 字段时，先按 reason 聚合分布检验或证伪当前因果假设，再沿「精确 reason 字符串 → 唯一 raise-site → 守卫谓词」反向定位代码，且只在产生该遥测的运行 checkout 中搜索；若日志只存 reason 不存 message，用最小受控复现补齐具体错误串。可避免两类绕路：未看 reason 分布就从消费者代码自顶向下猜原因；在镜像/默认分支里找只有运行线才有的发出点。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:658:b803f6cc6959a61ba946
evidence_refs: learning:learn:a20c6fa0b53a
created_at: 2026-09-17T15:33:06.156940+00:00
updated_at: 2026-09-17T15:33:06.156940+00:00
---
## Trigger
结构化日志/遥测出现重复失败或某计数只增不减，且事件带显式 reason/错误码字段；或已存在一个失败归因假设（如前台争用、超时）尚未对照 reason 分布检验。

## Discriminator
reason 字段的聚合分布（例：全部 requeue 均为同一 reason，候选竞争原因为 0 次）可在读任何深层代码前把候选原因层缩到一个；且精确 reason 字符串通常在运行线代码中只有一两个 raise-site，可被 grep 唯一命中。

## Short path
- 聚合 journal/遥测按 reason 字段的分布，先检验当前归因假设（如前台争用 vs 资源层拒绝），零计数的对照 reason 同样记录
- 在产生该遥测的运行 checkout（非镜像/默认分支）grep 精确 reason 字符串，定位 raise-site
- 读 raise-site 周边守卫条件，枚举触发该 reason 的全部谓词（状态、key、generation、limit 等）
- 若日志只存 reason 不存 message，按真实装配构造最小受控复现，捕获具体错误串以区分同 reason 的不同修法
- 修复并验证 reason 分布变化后，才恢复长周期观察窗——不在已知坏管道上继续积累观察数据

## Stop conditions
- raise-site 的守卫谓词已完整解释 reason 分布，且与产生遥测的 checkout 一致，转入修复
- 同一 reason 对应多种底层错误且日志无 message 时，停止静态推断，转最小受控复现
- reason 分布为多原因混合时按占比逐个追，不为单一假设强行解释全部事件

## Verification
- 最终 raise-site 的 reason 字符串与遥测中的值精确一致，且位于产生该遥测的运行 checkout
- 守卫谓词枚举覆盖 journal 中实际出现的每一种 reason，包括零计数的对照 reason
- 修复后 reason 分布按预期变化（归零或迁移到预期状态），再据此评估观察窗结论

## Counterexamples
- 日志已存完整异常 message/堆栈：直接按 message 分类定位，无需先追 raise-site
- reason 是多处复用的 catch-all（如统一的 failed）：分布无法缩到唯一 raise-site，应先补 message 捕获
- 失败源于环境瞬态（网络/配额/时钟漂移）：代码守卫谓词解释不了分布，应查外部依赖而非读代码
- 仓库只有单一 checkout 且即运行线：无需「选对树」步骤，方法退化为 reason→raise-site 两跳
