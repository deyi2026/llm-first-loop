---
method_id: atomic-write-edit-must-restore-exec-bit-on-executables-48a503855f1a
name: atomic-write-edit-must-restore-exec-bit-on-executables
description: 用回执标明『原子写入』（临时文件+rename）的编辑工具修改『必须可执行』的工件（git hook、entrypoint、启动脚本）时，执行位会被静默重置为 umask 默认（600/644），而『写后复读一致』只核内容不核 mode。此类编辑后的第一个跟进动作应是 mode 比对：ls -l / git diff --summary 看 mode 变更行，chmod 恢复原执行位，并把『diff 无 mode 行』纳入验证，避免『验证时 hook 不触发→排查脚本逻辑→最后才发现是权限』的绕路。本集编辑 pre-push hook 后被降为 600，事后才 chmod 755 补救。
aliases: hook 编辑后丢执行权限, 原子写入后脚本变600, 编辑工具掉了执行位, hook 不触发先查权限, 编辑可执行脚本后核对mode, git hook 权限被重置
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:fb85cea0-beb4-424d-b482-2819180ee46f:2443:dc1c3553574f2c223e53
evidence_refs: learning:learn:2b2c669096bb
created_at: 2026-11-09T17:51:51.155727+08:00
updated_at: 2026-11-09T17:51:51.155727+08:00
---
## Trigger
hook/launcher/entrypoint 等『必须可执行』的工件，被回执标记原子写入或整文件重写、且未明确承诺保留文件 mode 的编辑工具修改

## Discriminator
编辑回执同时给出两个当时已知事实：字样『原子写入』（机械上意味着临时文件+rename，mode 取自 umask，原有执行位必然丢失）+ 目标在 git 里原本是 100755/-rwx（git ls-files -s 或 ls -l 可见）。两者同时成立时，即使回执写『写后复读一致』也只证明内容一致、不证明执行契约未破坏。

## Short path
- 编辑前记下目标旧 mode（ls -l 或 git ls-files -s，如 100755）→ 未知量：编辑后必须恢复的执行契约是什么
- 编辑后立刻做一次 mode 比对（ls -l 目标，或 git diff --summary / git status）；出现 mode 变更行即为独立失败信号，不是外观差异
- 执行位丢失 → 立即 chmod 恢复旧值，并确认 git diff 不再出现 old mode/new mode 行
- 按真实调用路径做一次行为验证（如让 git 真触发一次 hook）成功即停止

## Stop conditions
- 编辑后 mode 与旧值完全一致（无 mode 变更行）且行为验证一次通过
- 目标从来不是可执行工件（普通文档/源码），无权限维度需要守护

## Verification
- git diff / git status 无 `old mode … new mode …` 行
- ls -l 显示执行位已恢复，且通过真实调用路径（hook 被 git 实际执行、脚本被直接 exec）成功运行一次

## Counterexamples
- 编辑普通文档或 .py/.md 源文件：mode 重置无功能影响，套用只会增加噪音
- 编辑工具是就地补丁型且明确保留 mode：判别事实不成立，无需额外步骤
- 脚本恒以 `bash x.sh`/`python x.py` 显式调起：执行位不属于其执行契约，丢失无行为后果
