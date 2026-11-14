---
method_id: receipt-metadata-recovery-for-truncated-command-output-dfc2e74e040f
name: receipt-metadata-recovery-for-truncated-command-output
description: 命令输出被传输层截断时，先读回执自带的范围/完整性元数据（恢复句柄、next_start、complete 标志、blob 身份）：有句柄就逐页水合到 complete:true；预估剩余量是数千行级就一次性物化成 scratch 文件再按锚点分段读。不要靠改写命令参数反复重试去拼回全量。回执没有恢复元数据时才退回收窄重试。
aliases: diff被截断继续读下一页, 工具输出截断怎么拿全量, 截断回执逐页水合到完整, 大diff先落盘再分段读, 回执带恢复句柄就别重跑命令
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:68f988f8-815b-4893-97c4-1a2da8a387f3:0:5336b8059f8f4c77b3ed
evidence_refs: learning:learn:104e81b2b717
created_at: 2026-11-14T08:55:33.193800+08:00
updated_at: 2026-11-14T08:55:33.193800+08:00
---
## Trigger
只读命令（git diff/stat/grep 等）的回执被截断：只见部分行，且回执携带 range/next_start/complete 或 blob 身份等恢复元数据

## Discriminator
回执是否自带 complete:false + next_start + 同一 blob 身份——这把『怎么拿全量』从无限种命令变体缩成一个确定的水合或一次性物化动作

## Short path
- 截断发生时先读回执元数据，确认恢复句柄是否存在及缺失窗口位置（next_start）
- 有句柄→按 next_start 逐页水合至 complete:true，核对各页与同一 blob 绑定
- 预估剩余为数千行级→一次性重定向物化到 scratch 文件，之后按任务清单锚点分段或检索读取
- 无句柄（纯失败、无范围元数据）→才收窄命令范围重试一次
- 取全后立即回到原审查未知量，不再发起同义命令

## Stop conditions
- 末页 complete:true 且各页归同一 blob 身份，即认定已获全量
- 物化文件规模与回执指示吻合，任务所需锚点已全部覆盖
- 无句柄且两次收窄重试仍失败→按任务协议如实记为局限/INCOMPLETE，停止枚举

## Verification
- 各页 next_start 链式衔接、range 校验值归属同一 blob_sha256、末页 complete:true
- 对物化文件用行数统计/锚点检索复核：被审条目（如逐文件 diff）确实全部在内

## Counterexamples
- 回执 complete:true（本就未截断）→直接使用，勿多余水合
- 回执是普通失败、无范围或恢复元数据→收窄重试才是正解，本法不适用
- 底层源在读取期间可变（快照与现势脱钩）→分页拼接可能是撕裂视图，须先钉版本或原子重取
