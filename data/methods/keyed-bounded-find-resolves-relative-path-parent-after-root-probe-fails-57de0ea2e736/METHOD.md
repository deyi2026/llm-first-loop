---
method_id: keyed-bounded-find-resolves-relative-path-parent-after-root-probe-fails-57de0ea2e736
name: keyed-bounded-find-resolves-relative-path-parent-after-root-probe-fails
description: 权威记录（裁定书/状态文件）以不带父目录的相对路径引用工件、按仓库根拼接的探测失败后，不要串行枚举猜想的父目录、也不要重发已超时的宽搜索：以引用中最独特的路径组件（罕见目录名/文件名）为键，做一次剪枝 heavy 树（.git/.venv/.worktrees/.releases）的有界遍历解析父目录，再用记录自带的指纹（sha256/行数）一击确认副本身份。本集 `s1d_pool/round2/` 副本实际在 evals/methodcard_rsi_v1/ 下，串行猜 data/docs/.research-notes 均落空且含一次超时；一次 keyed find 即可定位。另注意：evidence 台账只索引已读工件，物理定位失败后查它无新信息。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:e47f7009-17d2-450f-91a7-d4daf1887e55:1281:d98920b8bb5dfacd04d9
evidence_refs: learning:learn:d39eef28afa9
created_at: 2026-10-21T11:12:34.516605+08:00
updated_at: 2026-10-21T11:12:34.516605+08:00
---
## Trigger
已读的权威记录以相对路径或裸文件名引用某工件（无父目录信息），按仓库根拼接的第一次探测返回 No such file，且同仓库的无界搜索/遍历此前已发生超时

## Discriminator
引用中最独特的路径组件本身就是确定性检索键；记录同时给出可核验指纹（行数、sha256），命中后可一击确认身份；根目录枚举回执已暴露 .venv/.worktrees/.releases 等 heavy 树，须在遍历中剪枝

## Short path
- 探测失败后停止父目录猜想，把未知量收敛为『该独特名的父目录是什么』
- 执行一次剪枝的有界遍历（如 find . -maxdepth 5 -type d -name <独特名>，排除 .git/.venv/.worktrees/.releases），应秒级返回唯一父目录
- 对命中路径下同名工件计算 sha256/行数，与权威记录中的指纹比对
- 指纹一致即定位完成，进入内容操作（如双写回填），不再发起新的发现动作

## Stop conditions
- 父目录已解析且副本指纹与权威记录一致
- 有界遍历零命中 → 转为读设计/盘点文档解析真实基准目录命名方案，而不是继续换父目录枚举

## Verification
- 两个副本的 sha256 与权威记录中的指纹一致
- 剪枝后的遍历命令在秒级返回，未再触发 60s 超时

## Counterexamples
- 相对路径实为 store 键或 artifact:// URI 而非文件系统路径 → 文件遍历无效，应先读存储设计文档解析命名方案
- 独特名在多个镜像/快照中存在多份且记录未给指纹 → 无法一击确认身份，需按活树优先消歧
- 探测失败其实是名字抄错而父目录确在仓库根 → 先对照记录原文核对名字，不必找父目录
- 工具集只有精确路径读取、无 shell 遍历能力 → 本方法不可用
