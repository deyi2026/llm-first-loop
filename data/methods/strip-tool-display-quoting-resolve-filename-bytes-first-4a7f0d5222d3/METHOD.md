---
method_id: strip-tool-display-quoting-resolve-filename-bytes-first-4a7f0d5222d3
name: strip-tool-display-quoting-resolve-filename-bytes-first
description: git status --porcelain、ls 报错、shell 回显会把含前导空格等特殊字符的文件名包上引号（如 " sub" / ' sub'）。这些引号是显示层转义包装，不是名字的字节。把引号字符原样拼进下一条 ls/rm 命令会得到 No such file，据此宣布'已删除/不存在'就是假阴性。判别信号：权威清单（porcelain）仍列出该条目且名字被引号包裹，与早前'不存在'结论矛盾 → 第一未知量改为'名字的真实字节'，用与引号无关的通道（find -name / -print0|od -c / hexdump）一次解析，再下存在性结论或生成删除命令。
aliases: 文件名带引号查不到, 空格开头的文件怎么删, porcelain 双引号路径, 误报文件已删除 shell 引号, No such file 但条目还在, rm 前导空格文件名写法
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:8cdc10d0-aa2b-4b38-b050-e87862e63307:343:023040987a17f8a33335
evidence_refs: learning:learn:22e95e7950b2
created_at: 2026-10-28T00:37:37.896482+08:00
updated_at: 2026-10-28T00:37:37.896482+08:00
---
## Trigger
长任务收尾复核或写交接单时，需确认/转发一个早前输出中被引号包裹（或含前导空格、特殊字符）的文件名的存在性，或要为其生成 rm/mv 命令；尤其当早前曾有一次对该名字的探测返回 No such file 并被记为'已删除/不存在'。

## Discriminator
两条当时已可见的事实互相矛盾：权威清单（如 git status --porcelain）仍列出该条目，且其显示名被引号包裹（git 用双引号、ls 报错用单引号，均为转义包装）→ 说明名字含特殊字符且条目仍在，早前的 No such file 是探针名字写错，不是文件消失。

## Short path
- 看到任何输出中被引号包裹的文件名 → 把第一未知量定为'名字的真实字节序列'，禁止把带引号形式直接拼进下一条命令。
- 用与引号无关的探测解析字节：find <dir> -maxdepth 1 -name '<推测名>' -print，必要时 -print0 | od -c 或对文件名 hexdump。
- 字节确认后分支：存在 → 生成引用正确的命令（外部引号保护内部空格，如 rm -f "<dir>/ sub"）并更正早前误报；确不存在 → 才允许下'已删除'结论。
- 把正确命令与'引号是显示包装、不是名字一部分'的坑位说明一并写入交接文档，避免继任者重踩。

## Stop conditions
- 已取得字节级名字回执（find/hexdump 输出），且权威清单与探测结果的存在性一致
- 名字本轮早前已被 version_token/sha 或字节回执锁定且无新矛盾信号，直接复用不再重探

## Verification
- git status --porcelain 与 find -name 探测对同一名字给出一致的存在性结论
- 生成的删除/移动命令引用层级正确：外部引号保护内部空格，名字本身不含引号字符（除非字节回执证明含）

## Counterexamples
- 文件名字节里真含引号字符（人为创建的带引号名字）：不能预设'引号必是包装'，一切以字节回执为准
- No such file 的真实原因是 cwd/仓库根不对（名字在另一工作区）：先核对路径根，而不是纠结名字字节
- 输出来自不做显示包装的通道（find 裸输出、API 原始路径）：出现的引号就是名字本身，剥除反而造错
- 名字已在本轮被字节级锁定且无矛盾信号：无需重探
