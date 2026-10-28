---
method_id: preflight-shared-ci-gate-before-tag-push-raise-budget-not-code-e8b12d1c0b67
name: preflight-shared-ci-gate-before-tag-push-raise-budget-not-code
description: 推 tag 触发发布工作流前，若 main CI 已在带显式时间预算的门禁步骤（lint/type-check 棘轮）连续红，先消化该共享门再花 tag 推送；tag/CI 工作流在该步骤 fail-closed 超时、而本地同树同步骤已 exit 0（finding=0、耗时有余量）时，判为托管 runner 慢于本地+树增长的漂移而非产物回归：读日志失败行分类、本地计时对比，然后小提交调高 CI 预算或拆分步骤，保持质量语义不变；不改产品代码、不盲重试、不回滚。未发布的失败 tag 删除后在修复提交上重推，已发布 tag 绝不移动。用三个已得事实把『代码坏了？重试？回滚？』缩成『调预算』一个动作，并省掉整轮 tag 工作流的删除-重推循环。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5330df43-269d-4831-8ca6-e26379519674:512:c09d3fd19995585b28d4
evidence_refs: learning:learn:32585f0f25e9
created_at: 2026-10-20T15:13:31.131577+08:00
updated_at: 2026-10-20T15:13:31.131577+08:00
---
## Trigger
准备推版本 tag 触发发布工作流，且同仓库 main CI 最近连续多次在同一带时间预算的门禁步骤（如 pyright/type-check 棘轮）失败；或 tag/CI 工作流在该步骤 fail-closed 超时，而本地同树全量门禁此前已 exit 0。

## Discriminator
CI 日志失败行是预算超时击杀且诊断计数为 0（如 pyright new=0），不是真实 finding；本地同树同步骤全量门禁 exit 0 且耗时有余量；同步骤跨不相关提交连续复现而历史版本全绿。三者同现即环境/规模漂移而非代码回归。推 tag 前可得的先验事实：main CI 连续红 + 发布流程文档第 1 步本就要求确认 CI 状态。

## Short path
- 推 tag 前读 main CI 最近运行状态（发布流程首步本要求确认）；若共享预算步骤已连续红，先解决该门再推 tag。
- 失败后读工作流日志失败行，二分类：真实 finding vs 预算超时击杀。
- 同树本地复跑该步骤，记录 elapsed 对比 CI 预算，确认本地绿且余量充足。
- 小提交调高 CI 侧预算（或拆分/缓存该步骤），保持质量语义（new>0 仍 fail-closed）不变，预算提交本身走正常审查。
- 未发布的失败 tag 删除后在新修复提交上重推（已发布/稳定 tag 不动），重跑同一门确认 success 且对注入的新违规仍会红。

## Stop conditions
- 该步骤出现真实 finding（new>0 或测试红）→ 转产品修复，禁止以调预算掩盖问题。
- 本地同步骤同样超预算 → 需拆分/缓存/优化，单纯调预算只买一次时间。
- 超时表现为无输出挂起（infra hang）→ 查挂起根因（网络/死锁），与预算无关。
- 一次性 flaky 失败且无连续失败史 → 先查 runner 事故，最多一次受控重试，不动预算。

## Verification
- 预算调整后同一 tag 工作流 success（记录总时长），main CI 同步骤转绿。
- 抽查该门仍 fail-closed：注入一个新违规或临时调小预算应仍失败，证明改的是预算不是语义。
- 预算调整提交走正常审查与门禁；tag 删除与重推各过 push 审查并核对 remote/ref 目标。

## Counterexamples
- 失败是真实类型错误或测试失败 → 修代码；调预算等于 gaming 门禁。
- 本地跑不出且 CI 挂起无输出 → 网络/死锁类 infra 事件，预算无关。
- 独立工作流与 main CI 无共享步骤 → main CI 状态不构成它的预检依据。
- 单次超时、历史全绿 → 直接调预算会掩盖偶发故障，应先诊断再决定。
