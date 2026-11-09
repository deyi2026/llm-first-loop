---
method_id: guarded-writes-bind-location-via-tool-workdir-not-shell-cd-76157f170c89
name: guarded-writes-bind-location-via-tool-workdir-not-shell-cd
description: 在部署了写侧守卫的仓库里，于 git worktree/二级检出中提交或写文件时，命令内 `cd <worktree> && git commit ...` 不会改变守卫判定：守卫按工具调用面的结构化信号（workdir 参数、动作动词）分类位置与意图，shell cd 对它不可见，于是被误判为『在 main 提交』而遭 lane_main_write_conflict 拒绝。正确做法是从第一笔被守卫的写起就把 worktree 作为工具级 workdir 参数传入；收到位置类拒绝回执时，第一未知量不是内容是否合规而是守卫看到的根是哪个，直接以 workdir=<worktree> 原样重发即可，不做冲突诊断或绕行。
aliases: worktree 提交被守卫拦, 守卫说我在 main 提交, cd 到 worktree 还是判 main, lane_main_write_conflict 怎么过, worktree 里写操作要传 workdir
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:2321:96a808a191c4927d40f2
evidence_refs: learning:learn:d83906e2dbaf
created_at: 2026-11-08T20:19:43.818717+08:00
updated_at: 2026-11-08T20:19:43.818717+08:00
---
## Trigger
在 git worktree/二级检出内执行 git commit 等写操作，且仓库存在按工具调用面信号（workdir 参数、命令动词）判定位置与意图的写侧守卫或审计闸

## Discriminator
守卫拒绝回执给出的位置判定（如『在 main 提交』/lane_main_write_conflict）与命令事实（命令内已 cd 到 worktree）矛盾；同 run 早前回执已证明该守卫族按工具面信号分类（如探测载荷仅因含 push 动词即被拦）——说明守卫看不到 shell cd，其位置证据就是工具 workdir 参数

## Short path
- 在 worktree 内做任何会被守卫的写操作前，把 worktree 路径作为工具 workdir 参数传入，不依赖命令内 cd 定位
- 若已收到位置类拒绝（判 main/判越界）而命令确实 cd 在别处：以 workdir=<worktree> 原样重发同一命令，不进入冲突诊断或换通道绕行
- 重发通过后核对回执里的 cwd/分支字段与 worktree 实际路径一致，再继续后续动作

## Stop conditions
- 同一命令以 workdir=<worktree> 重发后守卫放行，且回执记录的位置与 worktree 一致
- 重发仍被拒但理由已变为内容类（如 staged 冲突、他人 staged 文件），此时转入该内容问题处理，不再调整 workdir

## Verification
- 守卫放行回执中的路径/分支与 worktree 实际顶层一致（可用 git -C <worktree> rev-parse --show-toplevel 对照）
- 主仓 main 侧 git status 未因这次提交出现新的 tracked 变化（写确实落在 worktree）

## Counterexamples
- 守卫实现改为解析命令字符串或探测实际工作目录（cd 生效）时，workdir 参数不再是唯一位置证据，需按其真实绑定面调整
- 仓库没有写侧守卫，或守卫只按目标 ref/动作判定而不关心位置时，无需此约束
- 只读操作（grep/ls/git log）守卫本就放行，不必为此强传 workdir
