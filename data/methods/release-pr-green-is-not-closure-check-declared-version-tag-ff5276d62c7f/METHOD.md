---
method_id: release-pr-green-is-not-closure-check-declared-version-tag-ff5276d62c7f
name: release-pr-green-is-not-closure-check-declared-version-tag
description: release PR 的 CI 全绿只证明质量门通过，不证明版本收口完成：tag 与 GitHub Release 是否存在于 merge commit 是独立不变量，发布工具链不会自动保证（本集 v0.6.30、v0.6.31 连续漏打，靠一次计划外的部署审计才发现缺口）。可复用判断：当任务对象是声明了版本号的 release PR、或状态面暴露 expected/actual 版本字段时，把『expected 版本是否已有指向 CI 绿 SHA 的 tag+Release』作为出结论前的确定性检查项——一条 git tag/gh release 查询即可裁定；缺失则按 tag 惯例确认属漏打、取 CHANGELOG 对应版本段作 notes、在 CI 全绿的精确 SHA 上补打。不要依赖『顺手审计』发现缺口，让声明字段直接驱动检查。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:1281:7e5bf02900f1784882b0
evidence_refs: learning:learn:7e3b870c024a
created_at: 2026-10-12T10:14:27.634751+08:00
updated_at: 2026-10-12T10:14:27.634751+08:00
---
## Trigger
任务对象是 release 性质的 PR（标题或任务声明了目标版本号，如 'release: vX.Y.Z'），CI 刚转绿、准备写『发布闭环/收口』结论；或任何状态面暴露 expected 与 actual 版本字段（如 expected_release_tag vs nearest_release_tag）不一致。

## Discriminator
knowledge-at-time：PR 标题在第 3 轮就已声明目标版本 v0.6.31，一条 `git tag -l`/`gh release view` 即可裁定该版本 tag 是否存在于 merge SHA；后续 runtime 又直接给出 nearest_release_tag=v0.6.29 ≠ expected_release_tag=v0.6.31 的显式不一致。收口缺口在成稿前就已被可观察事实标定——本集是靠一次计划外的部署审计才撞见它，若无该审计，『CI 全绿=发布闭环』的错误结论就会成立。

## Short path
- 从 PR 标题/任务面读出目标版本号（本集第 3 轮已见 release: v0.6.31）；未知量=收口对象是哪个版本。
- CI 转绿后、写终局结论前，先做一条确定性检查：`git tag -l <ver>` / `gh release view <ver>` 是否存在且指向 merge SHA；未知量=版本收口是否已完成。
- 若已存在且指向该 SHA：收口成立，直接汇总结论并停止，不重复打 tag。
- 若缺失：查最近 tag 序列确认惯例连续性（本集 v0.6.22→v0.6.29 连续，故 v0.6.30/31 属漏打而非新惯例）；未知量=该不该补。
- 从 CHANGELOG 取对应版本段作 release notes，在 CI 全绿的精确 SHA 上 `git tag -a` + push + `gh release create`。
- 用回执 URL/tagName 验证后收口停止；历史遗漏版本（如本集 v0.6.30）除非用户要求不回补。

## Stop conditions
- 目标版本 tag 已存在且指向已验证全绿的 merge SHA、Release 已发布 → 检查通过，不重复打 tag。
- CI 未全绿或仍在进行 → 禁止打 tag，先等门禁收敛（本方法前提是被 tag 的 commit 已过门禁）。
- tag 序列表明该仓库本就不逐版本打 tag、发布走其它渠道 → expected/actual 不一致属预期设计，不是缺陷，不补。

## Verification
- 补打回执包含可访问的 release URL 且 tagName 与目标版本一致（本集回执含 releases/tag/v0.6.31）。
- tag 目标 commit == 通过全绿 CI 的 merge SHA（本集 d93e9a700），绝不 tag 未验证 SHA。
- 下一次读取状态面时 expected/actual 版本字段收敛一致。

## Counterexamples
- 普通功能 PR（非 release、无版本号声明）：CI 绿即收口，套用本方法会制造多余 tag/Release。
- 仓库惯例为稀疏 tag 或发布不经 git tag：expected/actual 不一致属设计行为，不是缺陷。
- CI 红或仍在跑：即使版本字段暴露缺失也不得补打——不变量前提是被 tag commit 已通过门禁。
- tag 已存在但指向错误 SHA：属『指错』而非『缺失』，应走修正/重打流程，不适用本补打路径。
