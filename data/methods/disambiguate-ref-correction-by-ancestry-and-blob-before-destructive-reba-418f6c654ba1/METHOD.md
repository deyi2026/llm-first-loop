---
method_id: disambiguate-ref-correction-by-ancestry-and-blob-before-destructive-reba-418f6c654ba1
name: disambiguate-ref-correction-by-ancestry-and-blob-before-destructive-rebase
description: 用户一句话纠正 ref/remote 名（『不是 origin/main，是 X 才对』）且存在两种读法：仅换推送/同步目标，或要求父提交 rebase 到新 ref。此时不要按破坏性读法直接 rebase。先用三组机械事实给纠正分类：新 ref 的 URL 身份、它与当前基线的祖先方向与落后提交数、本批实际改动文件的 blob 等价性。若新 ref 是基线的严格祖先（基线领先 N 提交）且改动文件 blob 完全相同，rebase 是纯倒退、零内容收益，纠正几乎必然指目标 remote：按最小读法落地（仅加 remote 配置，不 fetch/push/rebase），把 N 与 blob 证据摆给用户并抛一句二选一确认。与『先钉权威远端再比较』互补：那卡管比较前提，本卡管纠正语义分类与破坏性操作闸门。
aliases: 被纠正基线先判断改目标还是改父提交, 落后祖先且文件相同就不必 rebase, rebase 前先算会倒退多少提交, ref 名纠正先跑祖先方向和 blob 比对, 用户换 ref 名先澄清语义再动手
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:20761eb6-10e4-4e71-ae2b-0465510a97d8:288:63ec04e527d9494a55cf
evidence_refs: learning:learn:b24faff6239c
created_at: 2026-10-27T18:40:41.943126+08:00
updated_at: 2026-10-27T18:40:41.943126+08:00
---
## Trigger
用户以一句话纠正某个 ref/remote 名（典型如『不是 <默认名 origin>/main，是 <新名>/main 才对』），而该纠正同时存在两种合理解读：仅指推送/同步目标，或要求把交付的父提交基线 rebase/切换到新 ref；两种读法的代价差异巨大（一个只改配置，一个会倒退提交历史）。

## Discriminator
三组当时即可取得的事实可把读法从两个缩到一个：① git remote get-url 确认新 ref 的 URL 身份与旧名确实指向不同仓库；② rev-parse 两 tip + merge-base --is-ancestor 得到祖先方向与落后提交数 N；③ 对本批实际改动的文件做 blob 哈希比对。若新 ref 是基线的严格祖先、基线领先 N 提交、且改动文件 blob 全同，则父提交读法=纯倒退 N 提交且不改变任何产物内容，纠正应读作目标 remote 而非 rebase 指令。

## Short path
- 纠正到达：唯一未知量=新 ref 指向哪个仓库 → 在含该 remote 的仓/镜像 git remote get-url 解析 URL 身份，不枚举全部分支清单
- 未知量=当前基线与新 ref 的相对位置 → rev-parse 两 tip，merge-base --is-ancestor 正反双向，得到祖先方向与领先/落后提交数 N
- 未知量=rebase 是否改变产物内容 → 对本批实际改动的文件逐一比对 blob 哈希（基线 vs 新 ref）
- 新 ref 为严格祖先且 blob 全同 → 按目标读法最小落地：仅在本工作树添加 remote 配置，不 fetch、不 push、不 rebase
- 向用户报告 N 与 blob 证据，抛出唯一澄清问题（指推送目标还是父提交）；仅在用户确认破坏性读法后才执行 cherry-pick/rebase

## Stop conditions
- 三组事实齐备：URL 身份已钉死、祖先方向与提交数已确认、本批改动文件 blob 等价性已验证
- 已向用户提出二选一确认，且全程未执行任何破坏性 git 操作（rebase/reset/force/覆盖式 fetch）
- 用户明确选定某一读法后，按该读法收尾并停止比较

## Verification
- merge-base --is-ancestor 两个方向各验证一次，确认方向与报告中的 N 一致，避免把『基线是新 ref 祖先』与反向混淆
- 改动文件在两侧 rev-parse blob 哈希逐一相等，才允许声称『rebase 不改变产物内容』
- 最终答复显式包含落后提交数与 blob 相同证据，使用户可凭一句话否决任一读法

## Counterexamples
- 新 ref 领先基线或已分叉（非严格祖先）：纠正更可能确指父提交，须评估 rebase/合并的真实内容收益，只换目标 remote 会漏
- 本批改动文件 blob 在两侧不同：『rebase 零内容收益』不成立，须先看内容差异再分类读法
- 读法唯一（仓库仅一个 remote，或纠正语句明确写出『父提交/rebase』字样）：跳过澄清问题，直接执行
- 纠正针对的是已产出的比较结果或报告（基线错了整批要重做）：此时不是目标-vs-父提交的二选一，应进入重验/重做流程
