---
method_id: single-static-ratchet-red-guard-diff-and-anchor-before-env-control-a830690185b4
name: single-static-ratchet-red-guard-diff-and-anchor-before-env-control
description: 门禁只有一条失败、且失败测试是纯静态对账守卫（AST 行数/计数/allowlist 与外置基线 fixture 比对，无 PTY/TMPDIR/env 依赖）时，即使检索命中『沙箱批量假红』经验卡也不要先做 base worktree 对照——单点失败分布本身已排除环境红。第一未知量取守卫逐条差分：单跑该测试让断言自己打印登记 vs 实测与未登记键；第二未知量是归属：读基线 fixture 自述 _meta.head_commit（登记锚点）与 base..HEAD 区间比对，再求差分文件名 ∩ diff --name-only：非空即候选引入真红，执行仓库 sanctioned 重登记脚本（不手改数值、不拆生产函数、按守卫前缀机检）；空集或锚点=diff base 才升级为口径漂移或环境归因。初始摘要两条事实直接剪掉整条环境对照分支。
aliases: 棘轮基线红了对不上实测, 单条测试红是不是环境红, 函数行数守卫红了怎么处置, 基线登记滞后代码涨了, ratchet 红要不要重登记, 沙箱假红经验卡触发条件不符
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:fb9d2fd4-22ec-46f0-9f10-3dd3f2341da5:402:af15d55c6db0c241a3ca
evidence_refs: learning:learn:aacc204fb7d7
created_at: 2026-10-31T23:24:55.922589+08:00
updated_at: 2026-10-31T23:24:55.922589+08:00
---
## Trigger
门禁/CI 输出仅 1~2 条失败且失败测试为纯静态对账守卫（AST 行数/计数/allowlist 与外置基线 fixture 比对，无 PTY/TMPDIR/网络/env 依赖）；或检索命中『沙箱批量假红』类经验卡但其触发条件（批量、跨模块、登记红全 STALE）与当前失败分布不符

## Discriminator
动手前已可见的两条事实：①失败摘要计数分布是单点红（1 failed / 328 passed），非批量跨模块；②按失败标识符 grep 后『基线 fixture + sanctioned 重登记脚本』成对命中。二者把候选空间缩成『登记锚点滞后于候选增长』单一假设，排除环境红，也排除读守卫实现推导规则的需要

## Short path
- 用项目权威解释器单跑该失败测试，让守卫断言自己打印逐条差分（登记值 vs 实测值、未登记键）——一次运行同时完成复现与 inventory diff
- 读基线 fixture 的自述 meta（登记锚点提交/生成口径），与 base..HEAD 的 diff 区间比对：锚点在区间之前且 diff 未触碰 fixture ⇒ 红是候选增长越过旧登记的确定结果
- git diff --name-only base..HEAD 与差分中的文件名求交集：非空 ⇒ 候选引入真红；空 ⇒ 才升级为环境/口径漂移归因（转既有 base 对照方法）
- 非空 ⇒ 执行仓库 sanctioned 重登记路径（专用脚本，不手改数值、不拆生产函数），按守卫要求的提交前缀走机检
- 机检/幂等校验回执 PASS 即停；未在权威环境跑绿的剩余步骤如实移交，不登记完成

## Stop conditions
- 守卫逐条差分已取得、problems∩候选 diff 非空已定归属、登记经 sanctioned 脚本更新且机检回执 PASS
- 或交集为空 / 仓库无 sanctioned 登记路径时，已升级到口径漂移排查、环境对照或人工裁决并停止自行处置

## Verification
- 同一解释器复跑该守卫测试，problems 为空
- 基线 fixture 的 diff 仅含 sanctioned 脚本的确定性输出（键排序/缩进/生成口径一致，无手改痕迹）
- 守卫要求的提交机检（前缀检查或幂等 --check）回执 PASS

## Counterexamples
- 批量跨模块红且含 PTY 耗尽 / OS errno 写拒绝证据：是环境红，必须先做 base 同条件对照，直接重登记等于把环境问题合法化
- 基线锚点即当前 HEAD 而数值仍不一致：计量口径或双实现漂移，应查口径实现而非重登记
- 守卫断言的是行为字面量而非外部 fixture 对账：不存在登记路径，需改断言或实现并单独裁决
