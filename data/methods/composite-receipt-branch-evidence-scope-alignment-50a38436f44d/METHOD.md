---
method_id: composite-receipt-branch-evidence-scope-alignment-50a38436f44d
name: composite-receipt-branch-evidence-scope-alignment
description: 复合（多对象）动作的整单回执判 failed、但受影响对象 live 已达 desired 时，不要把整单 status 当对象真相去重执行或改执行面。先读回执 evidence 文本还原逐对象结论，再对比核验面对象集与执行面对象集：核验面 ⊃ 执行面会使该动作结构性永不可能成功，并让状态面自我污染（永远没有后续成功回执可覆盖，failed 越积越多）。修法是让判据面=执行面、从既有 evidence 只读派生分支结论（对历史回执立即生效），不伪造 durable 成功回执；确需触碰执行面时先跑锁定它的契约测试，范围扩缩常被契约锁死。
aliases: 整单failed但服务其实起来了, 回执失败但进程已是新版本, 批量重启一直失败怎么排查, 状态面板和实际进程不一致, 核验范围大于执行范围
status: candidate
source_model: deepseek/deepseek-flash
source_episode_refs: episode:31ddb659-cdd0-4df1-b9bd-a10e0bcdc6d7:10522:c8f9d26801ceb1eb045b
evidence_refs: learning:learn:fc81a1061a27
created_at: 2026-11-02T23:02:57.749327+08:00
updated_at: 2026-11-02T23:02:57.749327+08:00
---
## Trigger
状态/回执面把多个对象标为 failed 或落后（stable 停在旧代、stage_facts 挂 failed、generation_lag 显示差 N 代），但 live 观测或操作员断言这些对象实际已达 desired；状态面源自覆盖多对象的复合动作整单 durable 回执，且该类动作可能已连续多轮判 failed。

## Discriminator
打开最近一张 failed 回执：其 evidence 文本是否已含逐对象结论（形如 A[ok] B[ok] C[ok] D[fail]），而整单 status=failed 只是聚合裁决。同一张 failed 回执里出现分支 ok ⇒ 整单 status 不是对象真相，矛盾在判据/回写层而非对象本身；此时第二个判别事实是代码里核验面的对象集是否大于执行面的对象集。

## Short path
- 用 store 类构造器中已可见的路径方案（<data_dir>/runtime/<actions 目录>）直接定位回执目录；不要做全盘 find（易命中无关的测试/临时目录，把排查引向错误位置）
- 读最近几张 failed 回执，把 evidence 文本还原成逐对象事实——未知量：各分支到底成没成
- 分支 ok 而整单 failed → 对比核验面对象集 vs 执行面对象集——未知量：不一致出在哪一面
- 核验面 ⊃ 执行面 → 根因是判据范围错位：修判据面（核验面=执行面），不动执行面；若确需动执行面，先跑锁定它的契约测试（范围扩缩常被既有测试以业务契约锁死）
- 分支结论从既有 evidence 只读派生，对历史回执立即生效；不伪造 durable 成功回执，也不靠重执行动作去刷新状态面
- 在未改动的历史回执上回放新视图，验证矛盾在数据层消失；若动作有 deferred 生效（如需等本轮 run 结束才真正重启），终局核验排到生效之后，不提前宣布收敛

## Stop conditions
- 逐分支结论与 live 观测一致，stable/stage_facts/generation_lag 的矛盾在数据层面消失，且 durable 回执字段原样保留未伪造
- 核验面=执行面已用命名+注释锁定（各面分别写清理由），执行面契约测试通过

## Verification
- 回放验证：对同一批未改动的历史回执跑新视图，确认被覆盖分支不再标 failed、effective lag=0，而 durable lag 照实保留
- 契约验证：先跑锁定执行范围的既有测试再决定是否触碰执行面；目标测试与 canonical 门禁通过
- deferred 动作排定时核验：等其终态落盘后再回报收敛，而不是本轮内宣布

## Counterexamples
- 单对象动作：整单 status 即对象结论，failed 就是失败，无需分支解析
- 回执 evidence 只有聚合结论、无逐对象细节：无法派生分支真相，应重新观测 live 或重新核验，不能靠显示层推断
- evidence 明确给出分支 fail（对象真失败）：按失败处理，不得因 live 看似正常就翻案，除非重新核验
- live 观测本身来自无关镜像/旧缓存：先确认 live 面的权威性，再判定矛盾方向
