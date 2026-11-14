---
method_id: commit-time-reanchor-pinned-head-on-shared-branch-8d5d48134b86
name: commit-time-reanchor-pinned-head-on-shared-branch
description: 任务钉死期望 HEAD/base SHA 并规定『HEAD 漂移或他人写入即 STOP』时，锚定校验是时刻性前提而非一次性前提：共享分支上外来者以新 commit 落盘会让 worktree 全程 clean，status 与目标文件内容复查都发现不了，唯一信号在 commit 图。在首次写/commit 前重跑 rev-parse HEAD + log <锚>..HEAD，commit 后断言 parent==锚；一旦发现漂移立即冻结现场（不 reset/push），用 reflog 重建时间线交上级裁决。与『写前 status/内容复查』卡互补：那张抓工作区未提交改动，这张抓已被外来者 commit 的垫层。
aliases: 提交前HEAD被别人动了, status干净但HEAD变了, 别的writer抢先commit了, commit叠到了别人的提交上, 开工校验和提交之间的并发窗口
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:3610:cadaaa6f19db16dd87e3
evidence_refs: learning:learn:826dce9eb82a
created_at: 2026-11-14T10:37:01.335647+08:00
updated_at: 2026-11-14T10:37:01.335647+08:00
---
## Trigger
任务文本给出精确期望 HEAD/基线 SHA，并把『HEAD 漂移或另一 writer 在写』列为 STOP 条款；预检通过后到首次写文件/commit 之间还有较长的读取与分类阶段（分钟级窗口）；目标在共享分支（OPEN PR、多会话 worktree）。

## Discriminator
外来并发者的痕迹是同分支上的新 commit（新增不同路径的文件），worktree 保持 clean：git status、目标文件内容或读回执身份复查均不可见。唯一可见事实是 commit 图不匹配——rev-parse HEAD ≠ 预检锚定 SHA、log <锚>..HEAD 非空、或新 commit 的 parent ≠ 锚——而这条可机械比较的锚任务文本本身已经给出。

## Short path
- 预检一次钉锚：rev-parse HEAD==任务给定 SHA、status clean、PR headRefOid 一致，并记录时刻
- 照常完成参考读取与逐文件 diff 分类；期间不得默认锚仍然成立
- 首次写文件前、以及 git add/commit 前一步，重跑一条锚校验：rev-parse HEAD && git log <锚>..HEAD --oneline；HEAD≠锚或列表非空（外来 commit）→ 立即 STOP，零本地写入，直接按时间线上报
- 锚仍成立 → 写 manifest、校验、安全扫描、带 hook 正常 commit（禁用 --no-verify），并在同一验证块断言 rev-parse HEAD^ == 锚定 SHA，再跑 gate 脚本
- 若 commit 后才发现 parent≠锚：冻结现场（不 reset/push/删文件），用 git reflog 重建权威时间线（外来 commit 的作者/时刻/内容、自己的 commit/reset 序列），把两份产物与各自一键回退选项交上级裁决

## Stop conditions
- 预检即失败（HEAD≠给定 SHA / 不 clean / PR 不符）→ 立即 STOP
- commit 前复查发现锚漂移或 <锚>..HEAD 出现外来 commit → STOP 并保持现场原样，不做任何写操作
- parent==锚、gate PASS、status clean、安全扫描 PASS → 正常收尾，报告精确 SHA/tree 与 exit 码
- commit 后才发现外来 commit 已垫在自己之下 → 停止一切 git 操作，只读取证（reflog/log）后上报

## Verification
- commit 前：rev-parse HEAD == 任务钉定 SHA 且 git log <锚>..HEAD 为空
- commit 后：rev-parse HEAD^ == 钉定 SHA，并与 gate 脚本、安全扫描同批运行
- reflog 时间线可完整复述外来 commit 的作者/时刻/内容与自己全部操作序列，与 STOP 报告一一对应

## Counterexamples
- 任务未钉 SHA、无漂移 STOP 条款：普通『干完提交』任务里重锚是多余仪式，叠在最新 commit 上可能正是预期工作流
- 并发者改动仍在工作区（untracked/未提交）：status --porcelain 即可发现，走内容/状态复查路径即可，无需 commit 图断言
- 独占新建 worktree 或保证单写者的分支：commit 前复查白费一步
- 流程明确要求先 rebase/跟进最新再提交：锚刚性反而违背任务意图
