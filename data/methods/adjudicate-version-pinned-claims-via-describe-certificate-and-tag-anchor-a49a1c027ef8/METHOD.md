---
method_id: adjudicate-version-pinned-claims-via-describe-certificate-and-tag-anchor-a49a1c027ef8
name: adjudicate-version-pinned-claims-via-describe-certificate-and-tag-anchor
description: 审核含版本号/发布状态/统计数字断言的稿件时，首个 git 探针返回的 describe 字符串（vX.Y.Z-N-gHASH）本身就是版本关系证书：N>0 即证明该 tag 已存在且是 HEAD 祖先，可立即裁决'已发布/未发布/最新版本'类断言，无需先做全量 tag 枚举或等基线取证完成。用户已点名版本区间时 tag 查询应带过滤避免输出截断重查；随版本变动的统计数字一律按 tag/commit 锚点重测并在结论中标注锚点，因为快节奏仓库的版本快照当日即过期，同日双发布更使稿件间版本矛盾成为预期发现。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:87454a3c-2a7c-4282-974a-24e435f8ebcb:1:c3cfd03d2ea7b04c2d29
evidence_refs: learning:learn:ec538a43c2b0
created_at: 2026-10-11T01:29:42.239502+08:00
updated_at: 2026-10-11T01:29:42.239502+08:00
---
## Trigger
审核/复核的对象文档引用了仓库版本号、发布状态断言（如'Unreleased/尚未发布'）或随版本变动的统计数字，且任务方已点名版本关系为核对重点；同时可取得 HEAD 的 git describe 输出或 tag 列表。

## Discriminator
describe 字符串 vX.Y.Z-N-gHASH：N>0 证明 vX.Y.Z 已打 tag 且是 HEAD 祖先，故稿件所称'最新版本/仍在 Unreleased'可能已失效；配合 CHANGELOG 是否存在 Unreleased 区与该 tag 提交日期即可一次性裁决。本案第 4 步已见 v0.6.28-12-g692aef752（证明 v0.6.28 存在且在 HEAD 之下），却仍经全量 tag 列举、被字典序截断后二次查询才确认 16:43 发布与 CHANGELOG 无 Unreleased 区。

## Short path
- 读取目标稿件并记录 SHA256 与工作区状态（M/??），首个 git 探针即用 rev-parse+describe，从 N 值直接判断最新 tag 是否新于稿件所引版本
- 若新于：只取该 tag 的日期与 CHANGELOG 对应版本段（而非全量 tag 枚举），立即裁决用户点名的版本关系断言
- 稿件中的行数/文件数/提交数等统计数字按该 tag/commit 锚点重测，修正建议与审核结论均标注锚点与统计时点
- 同系列多篇版本引用互相矛盾时，以 tag 时间线为唯一裁决来源，逐篇指出其事实快照停在哪一版
- 版本关系与统计锚点裁决完毕即停止版本面取证，转入其余核对项（引文/图片/版权）

## Stop conditions
- 用户点名的版本关系断言已被 tag 日期+CHANGELOG 双源裁决
- 所有随版本变动的统计数字已在指定锚点重测并在回执中标注
- 稿件所引版本与最新 tag 一致（N=0 且无更高版本段），版本面转常规逐条核对

## Verification
- 回执中每个版本断言都能回指具体 tag hash+发布时间或 commit hash
- 记录稿件 SHA256 与工作区脏状态：未提交/未跟踪稿件本身无版本锚，结论须声明依据的是工作区快照
- 统计数字与稿件旧值并列给出差值与重测口径（如 804→805、161,149→161,472）

## Counterexamples
- describe 显示 N=0 且 CHANGELOG 无更新版本段：稿件版本断言可能仍成立，不能凭'存在新提交'判失效，需逐条核对
- 稿件引用的是外部资源（arXiv 号、外部项目版本）：tag 证书不适用，必须按各自权威源核实，不可用本仓库状态外推
- 浅克隆/无 tag/无版本管理的目标：无 describe 证书可读，退回以 CHANGELOG/VERSION 文件为锚点
