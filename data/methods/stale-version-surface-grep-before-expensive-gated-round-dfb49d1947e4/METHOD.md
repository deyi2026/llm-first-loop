---
method_id: stale-version-surface-grep-before-expensive-gated-round-dfb49d1947e4
name: stale-version-surface-grep-before-expensive-gated-round
description: 候选 diff 对包元数据做了版本 bump（pyproject/wheel METADATA 出现新版本号）而未触及其他携带版本串的文件时，版本是跨文件不变量：语义审查会漏（本集 Reviewer 对 SERVICE_VERSION/README×2/CHANGELOG 四处陈旧面给出 PASS），一行一致性测试却确定性红。冻结候选投入昂贵门禁（长时异步审查、全量 CI、发布构建）前，先定向 grep 旧版本号枚举全部陈旧表面，按一致性测试源码的权威清单同步后再重算 SHA 送审，避免『审查 PASS→门禁版本红→修复→换 SHA 二轮重审』的双轮浪费，以及事后交付物指纹（wheel SHA）被替换引发的汇报混乱。
aliases: 升版本号要同步哪些文件, bump 版本前先全局搜旧版本号, 版本一致性测试红了先读测试源码定范围, 评审过了 CI 却版本红, 版本面没同步就送审白等一轮
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:2355:216c5e214e985f9a90bc
evidence_refs: learning:learn:9eab910aa7b3
created_at: 2026-11-08T15:42:19.275631+08:00
updated_at: 2026-11-08T15:42:19.275631+08:00
---
## Trigger
候选/提交 diff 含包元数据版本号 bump（新版本号已出现在 pyproject 或 wheel METADATA 回执中），而 diff 清单未触及其他可能携带同一版本串的文件（服务常量、README Version 标记、CHANGELOG 顶部条目），且下一步是昂贵的门禁轮次（数十分钟异步独立审查/全量 CI/发布构建）。

## Discriminator
diff 清单本身就是判别事实：版本承载文件已改、其余版本表面不在 diff 中。无需预知测试存在，一次定向 grep 旧版本串（如 0.6.40）即可在送审前枚举全部陈旧表面；若仓库有版本一致性测试，其源码就是权威表面清单。语义审查 PASS 不证明跨文件不变量——本集第一轮 full_test PASS 后 R9 即版本红。

## Short path
- 复核候选 diff 时识别出版本 bump；未知量：仓库还有哪些文件携带同一版本串？
- 定向 grep 旧版本号枚举全部版本表面（限定仓根文件，排除 .worktrees/.venv 等噪声目录）。
- 若存在版本一致性测试，读其源码取得权威表面清单；按清单同步各表面，CHANGELOG 条目依据提交说明撰写。
- 同步后重新冻结候选（重算树 SHA），再启动昂贵审查/门禁，一轮完成。
- 门禁仍红时，先读失败测试源码确定不变量覆盖的完整修复范围，不按报错信息单点修。

## Stop conditions
- grep 显示所有版本表面已等于新版本号——预检通过，直接送审
- 仓库为单一版本源（动态版本、表面由构建/发布工具生成）——无手写重复面可同步
- 用户契约钉死候选 SHA 且禁止送审前改动候选树——预检降级为『发现即上报/记入账本』，不擅自改树换 SHA

## Verification
- 送审前本地定向跑版本一致性测试（或等价 grep 断言）通过
- 审查回执 candidate_sha256 精确等于修复后重算的树指纹
- CHANGELOG 顶部条目、README 标记、服务常量逐项等于新版本号
- 最终汇报中的 wheel/候选指纹与修复后重建工件一致，不被首轮旧指纹污染

## Counterexamples
- 动态单源版本仓库：版本只写在 pyproject，其余表面构建期注入——grep 只命中构建产物，手动同步反而制造偏差
- 仓库约定 CHANGELOG/README 由独立发布 PR 统一更新——候选内同步属于越权扩大 scope
- diff 不含版本 bump（纯功能修复）——方法不触发
- 版本表面由 release 工具自动 bump（changesets/bumpversion 等）——手改会与工具冲突
