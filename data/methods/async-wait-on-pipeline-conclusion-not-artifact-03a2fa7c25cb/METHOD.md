---
method_id: async-wait-on-pipeline-conclusion-not-artifact-03a2fa7c25cb
name: async-wait-on-pipeline-conclusion-not-artifact
description: 等待异步流水线（CI/发布 workflow）产出最终产物时，不要把等待条件设为'产物存在'并用固定 sleep 盲轮询：流水线失败是吸收态，产物永远不会出现，存在性轮询注定超时；后台 job 完成也不会唤醒会话。应每步先查流水线结论（run list/view），失败立即读失败日志定位根因；仍需等待时注册定时唤醒按典型耗时接管，而非前台 sleep 碰运气。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:513:3d79acd9b843e9521f58
evidence_refs: learning:learn:9cf004b590ec
created_at: 2026-09-19T08:42:08.862790+00:00
updated_at: 2026-09-19T08:42:08.862790+00:00
---
## Trigger
设置（或准备设置）对异步流水线最终产物的等待/轮询：成功条件只有'产物存在'、用固定 sleep 循环等待、而流水线状态本身可查询时

## Discriminator
等待脚本的成功条件只有产物存在（如 release view 非空），而该产物的唯一生产者是可查询结论的流水线；失败一旦发生即为吸收态，存在性轮询必然 TIMEOUT；且后台 job 完成不会唤醒会话，固定 sleep 只能靠碰运气命中完成时刻

## Short path
- 设置等待前（或每轮迭代）先查产生该产物的流水线结论（按触发 tag/branch 过滤 run list/watch）——解决未知量：流水线是否已终止、结论是什么
- 结论=success→读产物并核对一致性；结论=failure→立即读该 run 的失败日志（如 --log-failed）——解决未知量：失败步骤与根因
- 仍需等待时注册定时唤醒（时长≈流水线典型耗时）接管后续动作，替代前台 sleep 盲轮询
- 唤醒后第一步重新查 run 结论再决定下一步（合并/重触发/发布），不重复盲等

## Stop conditions
- 流水线结论已被权威来源确认：success 且产物与预期一致，或 failure 且根因已定位并修复
- 已注册唤醒接管且当前没有前台阻塞等待

## Verification
- 等待逻辑包含对流水线结论的显式分支（in_progress/success/failure），failure 分支立即转入日志读取而非继续等待
- 唤醒/接管后的第一个动作与最新 run 结论一致：fail→读日志定位，success→核对产物后收尾

## Counterexamples
- 产物来自无法查询状态的第三方系统（无 run/conclusion API）→ 只能存在性轮询，但须设硬超时并把超时本身视为失败信号
- 流水线数秒内完成且环境不支持定时唤醒 → 短的同步 watch 可接受，无需排程
- 产物存在多个独立 writer、无单一权威流水线 → 只监控一条 workflow 会漏因，应回到产物核对+多源检查
