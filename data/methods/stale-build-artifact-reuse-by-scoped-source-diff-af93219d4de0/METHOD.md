---
method_id: stale-build-artifact-reuse-by-scoped-source-diff-af93219d4de0
name: stale-build-artifact-reuse-by-scoped-source-diff
description: 发布门禁要求构建产物与当前源码绑定（如 webui dist hash 绑定），而现有产物构建时间早于 HEAD 提交时，不靠时间戳直觉重建、也不盲信旧产物：先读产物内嵌的源内容标记（source_sha256/tracked 数），再对『产物上次匹配的已发布代 HEAD..当前 HEAD』做一次限定源路径范围的 diff——源范围零变更即旧产物仍是当前源的有效构建，直接复用发布（产物 hash 不变）；有变更才先重建。一步把『重建/复用/手工重算 hash/试错等 publish 拒绝』收敛为一次 diff。
aliases: dist 比最新提交旧要重建吗, 发布前旧构建产物还能复用吗, 用 git diff 判断前端产物是否过期, 构建产物源指纹标记校验, 产物时间戳早于 HEAD 不必盲重建
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4aea0dd4-3b3b-4874-8090-870678230df3:633:b1c3d96d2bfc831541cd
evidence_refs: learning:learn:dd696f7b4361
created_at: 2026-11-03T09:37:34.361650+08:00
updated_at: 2026-11-03T09:37:34.361650+08:00
---
## Trigger
publish/update 等发布动作的程序校验里含『构建产物与源 hash 绑定』，而现有产物的时间戳早于待发布 HEAD 提交（或产物与 HEAD 的新旧关系不明），需要在『直接复用旧产物』与『先重建』之间裁决时

## Discriminator
产物自身带内容寻址的源标记（如 .lfl-webui-source.json 的 source_sha256+tracked_files），且存在一个该产物曾与之匹配的已知发布基线（上一 desired 代的 git_head）；这两点把『产物是否有效』缩成一个可 diff 的未知量：源路径范围在基线HEAD..当前HEAD 内是否零变更

## Short path
- status 只读取当前 desired 代与 git_head（作为产物上次匹配的基线），确认无屏障无在飞
- 核代码根：HEAD=待发布提交、tracked 树干净（publish 硬前置）
- 读产物内嵌源标记与 mtime：mtime 不早于 HEAD 且标记在位→直接视为有效；早于 HEAD→只做一个限定源范围的 diff（基线HEAD..HEAD -- <源路径>），零变更即产物有效
- 源范围有变更→先重建产物再发布；零变更→直接单语义 update（publish+restart，带 expected_generation），不再做额外语义校验
- 回执核对 generation/git_head/产物 hash 与预期一致；action 受理后若 waiting_for_requester_exit，签发一次性延迟核验并停止本轮，不阻塞轮询

## Stop conditions
- 产物有效性已由『源范围零变更 diff』或新构建回执证实，且 update 已受理（拿到 action_id）即停，不在 run 内等异步收敛
- diff 显示源范围有变更时，重建完成并拿到新产物 hash 前不得发起 publish

## Verification
- 零源变更时，update 回执的产物 hash 应与基线代完全相同（同一 artifact hash 即复用成功的程序侧证据）
- 延迟核验：status(action_id) 终态 succeeded 且 live.git_head=desired.git_head、lagging 清空

## Counterexamples
- 产物无源标记、也无已知曾匹配的发布基线→无法推断有效性，直接重建，别做无基线的 diff
- 发布工具对过期产物会 fail-fast 并给出明确 expected hash、且重建便宜→先让程序校验可能比预检更省调用
- 源范围内含每次必变的生成物/版本戳文件→scoped diff 恒非零，须改用文档化 hash 方案对当前源直接重算比对
