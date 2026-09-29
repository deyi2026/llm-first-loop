---
method_id: enumerate-refs-same-path-before-reviewing-untracked-copy-b7ca5ef613f9
name: enumerate-refs-same-path-before-reviewing-untracked-copy
description: 当评审/自检目标在当前工作区是未入库（?? untracked）或脏副本，且存在『有更新』类信号或多分支活动痕迹时，不得把工作区副本当权威版本直接深挖。先用一条 git log --all -- <path>（必要时 git branch -a / git show <ref>:<path>）枚举同一路径在各 ref 上的全部版本，选最新已入库版本作为评审与复现对象；仅当全 ref 无其他版本时才以本地副本为准。本集因跳过这一步，整篇自检建立在 main 工作区的 R9 未入库副本上，而权威 R10 在领先 47 commit 的分支上。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:7bd90e8c-559a-47d4-8b0a-a458da824909:70:a41f67000ee11027b0be
evidence_refs: learning:learn:66c60bf34d0c
created_at: 2026-09-29T01:09:35.839622+08:00
updated_at: 2026-09-29T01:09:35.839622+08:00
---
## Trigger
用户提示存在更新/要求自检，或即将深入评审（读改记录、复现命令、打分）的目标文件在 git status 中显示为 '??' 未入库或脏副本，且仓库有多分支活动证据（如 merge commit），即触发：先裁决『哪份是权威版本』再投入分析。

## Discriminator
深挖前已可见三条事实任一即足够：(1) git status 回执明确标注目标文件为 '??' 未入库，回执还自带图例『空=已 tracked 且干净』；(2) 用户开场白明说『有更新』——更新点从未被定位；(3) git log 可见 'Merge branch ... into ...' 证明多分支并行。三者共同指向同一未知量：当前工作区副本是否该路径的最新版本，一条 git log --all -- <path> 即可裁决。

## Short path
- 用已知精确文件名 search_files 一步定位目标文件（不要按目录前缀猜测仓库根）
- git status 确认目标文件 tracked 状态；若为 '??' 或脏副本，把本地副本降级为『候选版本之一』，暂不作为评审基线
- git log --all --format='%h %ad %s' -- <path>（必要时 git branch -a）枚举同路径所有 ref 上的版本，比较日期/大小/修订号
- 若存在更新且已入库的版本，用 git show <ref>:<path> 或切到该分支读取权威版作为评审对象
- 对权威版执行原定自检（核对修订记录、复现命令、对照 canonical 数值），逐条映射后停止

## Stop conditions
- git log --all -- <path> 显示本地副本就是最新版本、或该路径从未有其他 ref 版本——此时以本地副本为准继续
- 任务明确要求评审的正是当前未提交的工作区状态本身
- 已对权威版本完成核对，所有结论可映射到该 ref+版本，不再回看旧副本

## Verification
- 评审引用的每个关键数字/结论都能标注来源 ref+版本（如『分支 a35e0f638 的 R10』），而非仅『我读到的文件』
- 复现命令必须打在权威副本上：实测值与该版本 canonical 值一致才可标 ✅，与过期副本字面吻合不构成验证
- 若收尾时从未定位到用户所说的『更新』是什么，视为自检未完成，回查跨 ref 同路径版本

## Counterexamples
- 目标文件已 tracked 且工作区干净，且任务范围就是当前 checkout 分支的已提交状态——工作区副本即权威，无需跨 ref 枚举
- git log --all -- <path> 为空：该路径从未入库、无任何其他副本——以本地文件为准继续
- 任务明确要求评审未提交的工作区改动本身（如『看看我未提交的修改』）——本地副本就是评审对象
- 目标不在版本控制内（纯日志、下载产物、缓存文件）——方法不适用
