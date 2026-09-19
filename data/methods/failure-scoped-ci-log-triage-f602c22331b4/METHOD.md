---
method_id: failure-scoped-ci-log-triage-f602c22331b4
name: failure-scoped-ci-log-triage
description: 当 PR/status 查询已按名称定位某个 FAILURE 检查时，下一步只取该检查的失败输出（如 --log-failed / 按 '##[error]'、FAIL 过滤），而不是拉全量 run 日志逐段翻。若日志开头是 runner 版本/镜像等 provisioning 样板，这是"查询未命中失败内容"的信号，应立即收窄查询范围，而非以近似参数重发同一宽查询。一次定向调用即可拿到门禁自身的失败消息（规则名+违规清单），再与 PR 列表中的栈式关系交叉定位根因（如基线错位），避免多次无信息样板日志往返。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:1247:284a9139c012d2b8bc25
evidence_refs: learning:learn:2fc539cca59e
created_at: 2026-09-19T03:27:51.875432+00:00
updated_at: 2026-09-19T03:27:51.875432+00:00
---
## Trigger
CI/PR 状态查询（如 gh pr view --json checks）已返回按名称标记为 conclusion=FAILURE 的检查，且带有 run/job id 或 detailsUrl，需要定位失败根因。

## Discriminator
两个当时已知的事实：(1) 失败检查的名称、conclusion=FAILURE 及其 run/job id 已出现在 PR view JSON 中——未知量已收窄为"这一个检查输出了什么错误行"；(2) 日志输出以 'Current runner version'/'Runner Image Provisioner' 等开头 ⇒ 当前查询拿到的是无信号样板，是重定范围的信号而非重试信号。

## Short path
- gh pr list（+目标/goal 状态）确定开放 PR 集合与栈式关系（如 slice4→slice5、两者 base=main）
- gh pr view <PR> --json checks,mergeable,state：按名称锁定唯一 FAILURE 检查与其 run/job id
- 一次失败范围调用：gh run view <run> --log-failed（或 job 日志管道 grep '##[error]|FAIL'），直接读门禁自身消息
- 若返回仅 runner 样板：立即换 --log-failed/--job 定向，不再重发同形宽查询
- 用失败消息中的违规清单交叉 PR 列表事实（父 PR 绿且各含单 manifest）推断基线错位→给出机械修复顺序：合并父 PR→update-branch→重跑→合并

## Stop conditions
- 已取得失败检查自身输出的错误行（含具体规则与违规项清单），足以归因
- 确认失败为 transient/基础设施问题（失败步骤无门禁消息）→ 转重跑或全量日志，本方法停止
- PR view 已内联展示失败原因，无需任何日志调用

## Verification
- 提取的失败消息能命名具体规则（如 'expected exactly one X'）并列出违规文件，且清单项可归属到某个开放 PR 的变更集
- 据此给出的修复不改动内容：仅合并父 PR + 更新分支基线后，原 FAILURE 检查应转绿

## Counterexamples
- 失败是 runner OOM/网络超时等 transient：失败步骤日志无门禁消息，收窄查询无实质内容，应重跑而非继续过滤
- PR 状态中已内联给出失败摘要（外部 required check 的 description），再取日志是多余动作
- 外部系统报告的 required check 没有可访问的日志 URL：gh run 日志不可用，必须去外部系统查询
