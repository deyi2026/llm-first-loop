---
method_id: timestamp-align-status-flag-with-artifact-mtime-before-restart-verdict-9842c70519c5
name: timestamp-align-status-flag-with-artifact-mtime-before-restart-verdict
description: 平台健康/部署状态里的 restart_required=false 是快照时点结论，不能直接回答“现在还要不要重启”。先做时间序对齐：取状态中已有的 live.started_at 与快照生效时间，再只 stat 本次改动涉及的工件 mtime；若 mtime 晚于进程启动，运行中进程必然不含新代码，布尔标志作废，判定需重启；反之标志可信。“怎么做”则依据 failed service actions 的失败原因（如 git_head 绑定不匹配）设计：以当前稳定 head 提交一次重启，拿到 action_id 回执后立即结束本轮（两阶段异步），下轮查终态，不空转轮询。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a8ca7a5d-9f35-462e-b02e-e13f15ff0023:325:a80fbd3a49bcf2571a54
evidence_refs: learning:learn:dc9048e99447
created_at: 2026-09-20T13:47:17.233333+00:00
updated_at: 2026-09-20T13:47:17.233333+00:00
---
## Trigger
用户追问“还需要重启吗/新代码是否已生效”，而部署/健康状态返回无需重启类布尔结论，且存在刚被修改、可能晚于进程启动时间的代码或配置工件。

## Discriminator
状态 JSON 当时已同时给出 restart_required=false、live.started_at=15:32:38 与快照 succeeded_at≈15:33：说明该布尔结论只覆盖快照时点。据此唯一未知量缩成一个比较——被改工件的 mtime（15:47）是否晚于进程启动时间。时间序一比即裁决，无需全机进程枚举或重复读状态。

## Short path
- 读一次部署/服务状态；未知量=平台是否已判定需重启；提取 restart_required、live.started_at、快照生效时间与 code_root。
- 只 stat 用户问题涉及的那几个被改工件；未知量=mtime 是否晚于 started_at；本例 15:47>15:32，布尔标志被时间序推翻→需重启。
- 若需解释“之前重启为何未生效”，只读一次 failed service actions：得到 git_head 绑定不匹配，作为本次提交策略的依据。
- 以当前稳定 head 提交一次重启，记录回执的 action_id/target/generation；按两阶段异步约定立即结束本轮，不轮询。
- 回复判定依据与用户操作指引；对 merge 触及的文件做定点 grep 确认接线仍在，然后停止。

## Stop conditions
- started_at 与 mtime 的比较已给出“需/不需重启”的裁决，不再读额外状态或进程表。
- 重启已受理且拿到 action_id 回执，用户操作指引已给出；终态留待下一轮 status 查询。

## Verification
- 对本次改动/merge 触及的文件做定点 grep，确认关键接线点（本例 4 个 checkpoint 调用点）仍存在。
- 下一轮查询重启终态，并复核新进程 started_at 晚于工件 mtime、generation/head 与提交时一致。

## Counterexamples
- 状态快照的生成时间晚于工件 mtime（快照在变更之后产出）：布尔标志本身权威，直接采信，勿做时间戳取证。
- mtime 更新但变更语义无关（注释、格式化、未进入运行路径）：单凭 mtime 会误判，需先看变更内容再裁决。
- 运行时支持热重载/按需加载，进程启动时间不代表实际代码版本：mtime 比较不适用。
- 用户问的是“重启请求是否已登记/绑定成功”：权威来源是 action 记录与回执本身，而不是文件 mtime。
