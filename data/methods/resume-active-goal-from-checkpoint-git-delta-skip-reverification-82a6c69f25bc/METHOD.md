---
method_id: resume-active-goal-from-checkpoint-git-delta-skip-reverification-82a6c69f25bc
name: resume-active-goal-from-checkpoint-git-delta-skip-reverification
description: 收到极简『继续』且存在活动 goal 记录（含『当前步』描述与带时间戳 checkpoints）时，先用 git log/worktree delta 对照 checkpoints 判定所述当前步是否已完成；若已完成，跳过对该步骤产物的二次核验与全目录枚举，直接进入下一里程碑，并从已完成产物自身的引用头（文档头部列出的权威源文档、正文引用的数据存档）拉取必读材料。goal 文本中的路径样标识可能是分支名而非文件名，应经 git 解析而非按文件名搜索。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d4b773f7-7796-4ff1-a76a-310f94b7feff:335:d744f2dbde4805fca78b
evidence_refs: learning:learn:459c0fadf6e8
created_at: 2026-09-25T13:28:20.746064+00:00
updated_at: 2026-09-25T13:28:20.746064+00:00
---
## Trigger
极简续跑指令（如『继续』）+ goal 查询返回 active，且记录含『当前步』描述与带时间戳的 checkpoints/进度日志；工作在已知 worktree/分支上。

## Discriminator
最新 checkpoint 内容与 git log HEAD 提交信息是否互相印证（如 checkpoint 写『入口条件全部关闭』且 HEAD commit message 与 diffstat 覆盖同一交付）。二者一致即证明 stated 当前步已完成，续跑点在其后；同时 goal 文本里『提交到 <path>』样标识在文件名搜索 miss 时应判定为分支名。

## Short path
- 查 goal 记录，取得『当前步』文本 + checkpoints 时间线（未知量：任务进行到哪）
- 对 worktree 执行 git log --oneline（含 diffstat），对照最新 checkpoint：若 HEAD 提交已兑现当前步承诺，标记该步完成，不再重读其产物细节做二次核验（未知量：stated 当前步是否已成）
- 从已完成产物的显式引用确定下一阶段必读集：需求/整合文档头部列出的权威源文档 + 正文引用的数据存档，逐个读取（未知量：开工前还缺哪些权威输入）
- 标识解析：goal 文本中的 'docs/<name>' 若文件名搜索 miss，视为分支名走 git，不继续换 pattern 搜文件
- 必读集读完后直接进入下一里程碑实施，不再做目录级发现

## Stop conditions
- checkpoints 与 git HEAD 互相印证证明当前步完成，且下一阶段必读权威材料（均来自显式引用）已读完 → 停止发现，开工
- git delta 与 checkpoint 矛盾（承诺的提交缺失、工作区脏）→ 中止跳步，先做状态审计

## Verification
- 每个『必读源文档』都能回溯到已完成产物的显式引用（header/正文引用），而非目录枚举或宽搜索命中
- 续跑后首个实施动作与 goal 的下一里程碑直接对应，且未包含对已完成步骤的重复核验读取

## Counterexamples
- goal 记录只有『当前步』文本、无 checkpoints/进度日志 → 无完成证据可用，仍须实际核验产物与提交状态，不能跳步
- checkpoints 与 git HEAD 不一致（工作区有未提交改动或提交缺失）→ 完成证明不成立，须先审计差异
- 用户的『继续』指向临时插入的新意图而与 goal 当前步无关 → 先与 goal 对齐再决定续跑点
