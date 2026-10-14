---
method_id: recover-truncated-recon-via-scoped-rerun-not-byte-hydration-35ba2d349bee
name: recover-truncated-recon-via-scoped-rerun-not-byte-hydration
description: 批量侦察命令输出截断时的恢复策略选择：若缺失段所属对象（文件/条目）可从回执推出、且底层数据源可幂等重读（磁盘文件、grep/ls/仓库），则直接对缺失对象跑一次窄范围命令，而不是对截断 blob 做字符偏移 hydration。本集缺失段约 45+ 行 import，而 hydration 单次只回 60 字符，猜偏移一击不中后仍需整段重取；把『先试一次字节定位』换成『立即按对象名窄重跑』可省掉试探调用并一次闭合缺口。仅当数据源一次性或截断极小且回执已给精确 offset 时才走 hydration。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1897dc0c-c278-413c-b54d-22c50b97372f:96:ac23ea1f354bf0721695
evidence_refs: learning:learn:2e06957df97a
created_at: 2026-10-14T01:13:32.466698+08:00
updated_at: 2026-10-14T01:13:32.466698+08:00
---
## Trigger
一次枚举多对象的长侦察命令（批量 grep / 拼接 for 循环 / 多文件 ls）回执被截断，缺失的中尾段内容仍被当前未知量需要

## Discriminator
回执已暴露缺失段属于哪些具名对象（由命令序列+已显示前缀可推出），且该对象内容可由幂等命令重新生成；同时缺失段规模（数十行）远大于单次 hydration 粒度（约 60 字符）——此时一次窄重跑必然优于逐段猜偏移

## Short path
- 从截断回执确定已覆盖对象与缺失对象清单（本次为 3 个具名文件的 import 段）
- 判断缺失内容源是否可幂等重读：磁盘/仓库文件→是；一次性状态（进程/网络捕获）→否
- 可重读→对缺失对象跑窄命令（只列这几个文件），一次取得完整精确输出
- 一次性→按回执给出的精确 offset 做 hydration，不使用猜测偏移；合并观察后立即回到主任务

## Stop conditions
- 缺失对象已由窄重跑取得完整内容，且与回执元数据（对象数/行数）对上
- 确认缺失段与当前未知量无关，直接放弃恢复不补调用

## Verification
- 窄重跑输出覆盖此前全部缺失对象且自身未再截断（对象多时按对象分批）
- 恢复内容与首次已显示部分无矛盾（同一文件前后 import 一致）

## Counterexamples
- 输出来自有副作用或一次性命令（live 进程 dump、CDP 会话快照、竞态窗口抓取），不可重跑——必须走 evidence 字节区间恢复
- 截断只缺几行且回执已给精确 next_start——单次 hydration 比重跑整条命令便宜
- 重跑代价极高（数万行全量测试输出）而 evidence 已完整捕获原文——区间恢复优先，重跑反而是绕路
