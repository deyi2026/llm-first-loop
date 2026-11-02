---
method_id: batch-identity-matrix-before-workspace-advice-7b63bcea5802
name: batch-identity-matrix-before-workspace-advice
description: 对『给这个目录提建议』类开放任务，若首探针已证明根目录不是 git 仓库而是多子项目容器，下一个未知量应是顶层条目的身份矩阵（是否repo×活跃度×体积），用一次批量循环解决；初始 ls 的 mtime 梯度已给出活跃前沿排序，先做全树内部枚举属扩散。把身份与价值信号交叉，可稳定产出『保护倒挂』类高价值发现：最重要产物无版本控制、巨型 vendored 树未 ignore；零散逐目录拼凑身份信息会拖慢并稀释结论。
aliases: 多仓库工作区怎么提建议, 目录体检先摸底再深挖, 先查哪些子目录没进git, 按修改时间找活跃项目, 巨型第三方源码目录误入库排查
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:40d20564-ac46-4792-b62c-f0b083523714:22:71e3a7147323ebfebfff
evidence_refs: learning:learn:98f7ec6adf54
created_at: 2026-11-01T20:23:00.028793+08:00
updated_at: 2026-11-01T20:23:00.028793+08:00
---
## Trigger
用户对一个本地路径提出开放式建议/体检请求（『对 X 你的建议是？』），首探针显示该路径不是单一 git 仓库，而是含多个子项目与杂项目录的容器（根 git 命令退出码 128 + ls 呈现多个独立项目目录）

## Discriminator
第一条 ls 回执里已含两条可判别事实：根目录 git 命令退出码 128（容器而非仓库）；各顶层目录 mtime 呈明显活跃梯度（数个近一两天、数个停滞数月）。这两条当时已把『处处都可能重要』缩成『先对十几个顶层条目各做一次批量身份探测』，无需先枚举目录内部结构

## Short path
- ls 根目录 + 根 git 探针：确认容器结构（本集首条命令已给出）
- 一次 for 循环批量分类全部顶层条目：git rev-parse/当前分支/dirty 计数 + du -sh，得到 版本身份×体积 矩阵，并用首条 ls 的 mtime 叠加活跃度排序
- 只对活跃前沿（mtime 最新、含 HANDOFF/交接类文档的目录）读状态文档，作权威锚点交叉验证
- 仅对矩阵异常点定点下钻：非 git 的高价值小目录、dirty 仓库的巨型未跟踪路径（对照 .gitignore 与 du 回执）
- 每条建议挂一条直接工具回执（status/check-ignore/grep/du），矩阵覆盖完即停止枚举，输出分级建议

## Stop conditions
- 全部顶层条目均有身份判定（git/非git、分支、dirty、体积），且每条输出建议都有直接工具回执支撑，不再出现新的待验证异常点

## Verification
- 用 git check-ignore 或 status 回执复核『未忽略的未跟踪大目录』判定
- 重跑身份循环，确认非git/dirty 判定与首测一致
- 抽查活跃前沿：mtime 最新目录确有最新交接/状态文档，而非备份恢复造成的假新鲜

## Counterexamples
- 根目录本身就是单一 git 仓库（git log 成功）：不做容器矩阵，按单仓审查流程
- 用户问的是某具体子项目的具体问题（如 CI 为何红）：直接进该项目状态文档，不做全工作区分级
- 目录从备份整体恢复导致 mtime 全部趋新：mtime 梯度失效，活跃度应改用各仓 git log 日期
- 工作区只有两三个顶层目录：批量分类开销大于收益，直接逐个看
