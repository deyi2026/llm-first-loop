---
method_id: locate-store-via-runtime-source-grep-not-filename-sweep-a75b034e2fd1
name: locate-store-via-runtime-source-grep-not-filename-sweep
description: 猜目录名定位持久化 store 落空（如 data/goals 为空），而更早的权威工具回执已证明该账本存在且由本仓库自己的 runtime 读写（如『账本内仍有 91 个 active goal』）时，不要做文件系统级全量文件名枚举——在带归档树（.releases）的仓库里它只会返回大量重复陈旧副本、无法区分权威存储与影子；应直接 scoped grep 运行时源码中该 store 的构造器/根路径符号，从定义处拿到真实根目录，再一次 ls/count 确认已填充；若仍需分辨权威与审计影子，用写方向 callsite 裁决后停止。
aliases: 猜的 data 目录是空的怎么找真实存储, 全仓 find 全是 .releases 重复副本, 先 grep 源码找存储路径, goal 台账到底在哪个目录, 区分权威存储和归档副本, 回执说有账本但不知道存哪
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a6989bff-e814-43eb-9f8a-a24f42790dd9:97:fd5bc1fb0bfe68c7a2ca
evidence_refs: learning:learn:3edf28dbf709
created_at: 2026-11-05T23:30:47.461848+08:00
updated_at: 2026-11-05T23:30:47.461848+08:00
---
## Trigger
按目录命名习惯猜测的持久化 store 路径实测为空，同时之前的权威工具回执已明确声明该 store 存在且有记录（例如 degraded 警告里写出『账本仍有 N 个 active』），且读写它的代码就在当前仓库的 runtime 源码内

## Discriminator
回执证明 store 是被本仓库自身 runtime 机器读写的 → 其根路径必然出现在源码的构造器调用或路径常量处，一条 scoped grep（如 GoalStore/audit_dir）即可命中；而文件系统级文件名搜索在含 .releases 归档树的仓库里会返回多份重复副本（同一 GOAL 文件出现在多个 release 快照），该对比在选择搜索方式之前就已经成立

## Short path
- 猜测目录为空后，把未知量定为『store 根路径在源码何处定义』，对 src 做 scoped grep 构造器/根路径符号，不做全仓文件名枚举
- 从 grep 命中行直接取出真实根目录（如 GoalStore(str(audit_dir)) → data/audit/tasks）
- 一次 ls/count 确认该目录已被填充，区分活存储与空壳
- 若任务还需区分权威存储与审计/归档影子：看构造与写入方向（谁写、谁只读），裁决后即停

## Stop conditions
- store 根目录已从源码定义处取得，且一次 ls/count 确认填充
- 回执或设计文档已直接给出规范路径，无需再定位

## Verification
- 用权威工具回执给出的计数交叉核对定位到的目录内容规模（如账本 91 active vs 目录内记录数）
- 确认 grep 命中是真实构造/读写 callsite，而非文档字符串、测试代码或历史归档

## Counterexamples
- store 由外部系统产生，本仓库源码不含其路径定义（如第三方工具缓存）→ 源码 grep 会落空，文件名级发现或官方文档才合适
- 路径由环境变量/配置注入而非硬编码 → grep 只命中变量名，仍比全量搜索窄，但需补一步读配置值
- 任务只需数据本身且回执已给出参数化全量查询（如『传 window_hours=0 查看全部』）→ 直接按参数重查，不必下沉到文件层定位
