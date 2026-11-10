---
method_id: exec-bit-guard-disk-stat-not-git-baseline-prove-red-per-vector-b4a19324d89a
name: exec-bit-guard-disk-stat-not-git-baseline-prove-red-per-vector
description: 安全关键脚本（git hooks、安装器）的执行位/rw 位丢失若已静默复发过，修复不能停在再 chmod 一次：守卫断言的层次由表示限制决定——git 索引只记 x 位，磁盘 711 在索引里就是 100755，凡以 git 为基线的检查对 rw 位丢失天然失明。真值层必须是磁盘 stat（owner/非 owner 分别断言 x 位，或整体 0o755），索引 100755 作独立第二层，文件/目录缺失时 fail-closed。每个断言维度用对应破坏向量实测一次红（chmod 644→磁盘层红；update-index --chmod=-x→索引层红），恢复后全绿才可信——从未见过红的绿灯不是门。安装类修复做成幂等脚本：写后回读校验，钩子缺执行位拒装。
aliases: 钩子执行位又丢了怎么加守卫, 711在git索引里就是755, 权限测试没红过不算门, chmod后执行位静默变化怎么拦, 权限守卫断言磁盘还是索引, 负例实测守卫能不能红
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:575:a63f4154074fc17c6fcd
evidence_refs: learning:learn:e82b548108c5
created_at: 2026-11-10T07:55:22.127966+08:00
updated_at: 2026-11-10T07:55:22.127966+08:00
---
## Trigger
为仓库内安全关键脚本（git hooks、安装脚本）补权限守卫测试，或执行位丢失已静默复发过至少一次；现有权限检查依赖 git 状态（索引 mode / diff / 历史提交记录）作为判据

## Discriminator
首轮 ls/stat 的磁盘 mode 与 git 可表示模式集之差：索引只有 100644/100755 两态，rwx--x--x（711）这类磁盘输出在 git 侧完全合法——任何以 git 为基线的检查都抓不住 rw 位丢失，磁盘 stat 是唯一信息完整的真值层

## Short path
- 从首轮目录列表取磁盘真值（如 711/600），一次 git ls-files -s 取索引 mode，立即得出『索引断言对 rw 位失明』——先定断言层，再写测试
- 分层写守卫：磁盘 owner x 位、非 owner x 位（或整体 0o755）＋ 索引 100755；钩子文件/目录缺失时 fail-closed（看不见的闸等于没有闸）
- 修复落盘用 chmod（不进 git 历史）；安装/配置修复写成幂等脚本：写后回读校验，钩子缺执行位拒装，--force 才覆盖他人配置
- 负例矩阵逐向量实测：chmod 644 → 磁盘层用例必须红；git update-index --chmod=-x → 索引层用例必须红；恢复 755 后全绿
- 任一断言维度没被证明能红，就不宣布收口

## Stop conditions
- 全部断言维度均被对应破坏向量证明能红一次，且恢复后全绿
- 磁盘层与索引层断言齐备，文件/目录缺失的 fail-closed 场景已覆盖

## Verification
- chmod 644 后磁盘层用例转红；git update-index --chmod=-x 后索引层用例转红；恢复后全部 passed
- 安装脚本重跑报告『已安装』（幂等）；人为去掉执行位后重装被拒绝

## Counterexamples
- 文件不受 git 管理：没有索引层，只适用磁盘 stat 断言，索引断言维度不存在
- 单用户/容器内运行且 rw 位差异无行为后果：owner/非 owner 分层断言冗余，一条 x 位断言即可
- 权限设计为部署时动态 chmod：静态磁盘 mode 断言会误报，应守卫安装器行为而非固定 mode 值
