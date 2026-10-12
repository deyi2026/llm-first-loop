---
method_id: failed-ci-gate-diagnose-from-local-gate-script-repro-04eed411f3de
name: failed-ci-gate-diagnose-from-local-gate-script-repro
description: CI 门禁失败阻塞合并/部署时，不要反复翻整段 run 日志（多为 runner/setup 样板）。先只取失败步骤专属日志段；失败步骤的命令通常已点名一个仓库内门禁脚本及其 --base/--head 入参——把该脚本当作失败的权威定义：读脚本与所需工件目录（既有清单即模板），用 CI 同样的 base/head SHA 在本地复现门禁（若 CI base 与本地 parent 不一致，先 fetch 再算真实差分），本地迭代到 PASS 后再推送一次，重跑全绿才合并/部署。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:2240:c787e290bba474a788b2
evidence_refs: learning:learn:2fa4e4ad1090
created_at: 2026-09-22T16:38:28.597384+00:00
updated_at: 2026-09-22T16:38:28.597384+00:00
---
## Trigger
PR 上某项 status check 为 FAILURE 且阻塞合并/部署（如用户约定"没问题才部署"），且 run 元数据/日志中可见失败步骤实际执行的命令。

## Discriminator
首次查看失败 run 时已可见：失败步骤运行的是仓库本地脚本（带显式 --base/--head 参数），且检查名自述为机械 presence/coverage 类检查——失败定义就在仓库内、可本地复现；而普通 gh run view 输出多为 runner/setup 样板，继续翻页不会缩小任何未知量。同时可见 CI 的 base SHA 与分支 parent 不一致（main 已前移），真实差分需重新计算。

## Short path
- 多 remote worktree 下 gh 命令显式带 --repo（必要时先 git remote -v 消歧），查看 PR 状态，定位失败 check 及其 run/job 链接。
- 只取失败步骤日志段（gh run view --log-failed 或按 job 取 log），拿到精确失败信息；未知量：到底违反了什么。
- 失败步骤命令已点名仓库内门禁脚本及入参 → 本地读该脚本 + 其所需工件目录（既有清单即格式模板）；未知量：权威要求与样例。
- 用 CI 同样的 base/head SHA 本地复现门禁（CI base ≠ 本地 parent 时先 fetch main 再算真实差分），迭代修复到本地 PASS。
- 推送一次并等待重跑；所有必需 check 全绿后才合并/部署。

## Stop conditions
- 用失败步骤同款脚本、同款参数在同一 base..head 区间本地跑出 PASS。
- 失败为瞬态基础设施问题（报错指向 runner/网络而非策略违规）——直接重跑而非改代码。
- 失败步骤无仓库内定义（外部 SaaS/托管检查）——停止本地复现，只依赖 annotations/厂商文档。

## Verification
- 本地复现使用的脚本路径与 --base/--head SHA 与失败 CI 步骤中显示的完全一致。
- 推送后 CI 重跑中原失败 check 变 SUCCESS，且其余必需 check 全绿，才执行合并/部署。
- 补交的工件精确满足门禁的"恰好数量/分区"要求，无缺失或多余条目。

## Counterexamples
- 失败 check 是外部服务（SaaS 安全扫描、托管 API），无仓库内脚本可读可复现——只能用 annotations 和厂商文档。
- 失败信息本身已完整列出可操作错误（如缺失文件的精确清单）——直接修复即可，再读门禁源码属多余动作。
- 瞬态 infra 失败（runner OOM/网络超时）——本地复现会假绿，须先由报错文本区分策略失败与 infra 失败。
- CI workflow 检出的门禁脚本版本与本地 checkout 不同（不同 ref/pin）——本地结果与 CI 背离，须先核对 workflow 实际检出的脚本版本。
