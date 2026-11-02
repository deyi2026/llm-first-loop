---
method_id: eperrm-clean-perms-read-declared-write-root-not-path-ladder-d9613ec6114c
name: eperrm-clean-perms-read-declared-write-root-not-path-ladder
description: 写目标路径报 Operation not permitted，但 owner 权限/ACL/挂载/会话 write-scope 全部清白时，边界由环境而非路径定义：先一条 env 检索读出环境自己声明的可写根（workspace/sandbox 类变量），用『声明根 vs 目标』两点写探针定案，再用一次显式 workdir=目标 的反证探针区分参数锚定与宿主配置。反证失败即判宿主配置边界：停止逐路径试写与逐通道碰运气，改为把完整交付物落到 /tmp 等可写区、同构 dry-run 验证后转交用户并给出执行选项。与 workdir 重锚类卡互斥：那张在反证成功时适用，本卡在反证失败时适用。
aliases: 写被拒但权限没问题怎么排查, Operation not permitted 权限正常, 沙箱可写范围由什么决定, git init 写不进去 EPERM, 从环境变量找可写根, 宿主写边界转用户执行
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:40d20564-ac46-4792-b62c-f0b083523714:55:3b19df288890b10d9e23
evidence_refs: learning:learn:9e47b665ca42
created_at: 2026-11-01T22:07:52.053037+08:00
updated_at: 2026-11-01T22:07:52.053037+08:00
---
## Trigger
对目标路径的写操作（touch/mkdir/git init）返回 Operation not permitted，而一轮廉价排查已排除本地原因：owner 有 w 位、无 ACL、非只读挂载、会话 write-scope 回执为全量；且无任何回执横幅声明可写范围。

## Discriminator
摩擦点前已看见的事实组合已足够收窄：目标属主 rwx、无 ACL、数据卷挂载可写、会话 write-scope 回执=全量且零越界记录，而 touch/mkdir/git init 一律 EPERM——排除文件权限/ACL/只读盘/会话授权后，唯一剩类是环境级（OS 沙箱/宿主）边界。这类边界的定义通常就在 shell env 的 workspace/sandbox 声明变量里，一条 grep 可读，无需逐路径枚举可写性。

## Short path
- 写失败 EPERM 后，一条命令打包排除本地原因：ls -ld 目标、ACL、挂载、会话 write-scope 回执；勿先枚举其他路径
- 全清白 → 读环境声明：env | grep -iE 'workspace|sandbox|root|home'，找命名可写根的变量
- 两点验证：touch 声明根（应 OK）+ 目标（已知 FAIL）→ 可写集=声明根树(+/tmp)，边界判定完成
- 参数反证：一次显式 workdir=目标 的最小写探针；仍 FAIL → 宿主配置边界，停止探测更多路径与通道（子代理/edit_file 等逐一尝试属浪费）
- 转交：把完整可执行交付物落到可写区（如 /tmp 脚本），用同构模拟目录 dry-run 验证纳入/排除断言，再向用户给出明确选项（代跑/改宿主配置/只读推进攒批次）

## Stop conditions
- 声明根可写、目标不可写、workdir 反证失败三者齐备 → 判定宿主配置边界，立即停止通道枚举，进入转交/升级
- env 中不存在任何 workspace/sandbox 声明变量 → 回退到有界阶梯探测（$HOME、/tmp 两三点）即止，不无限枚举
- 任一探针发现目标实际可写或某通道确有写权 → 停止边界排查，回到任务本身

## Verification
- 两点写探针结果与 env 声明根一致（根 OK、目标 EPERM）
- workdir 反证探针真实执行且失败被记录，据此显式作废旧 workdir 重锚经验而非默默沿用
- 转交物通过 bash -n 与同构目录 dry-run 断言（纳入/排除全 PASS），并预留用户执行后的回读核对入口（如 commit SHA 回验）

## Counterexamples
- ls -ld 显示 owner 无 w 位或存在 deny write 的 ACL → 文件系统问题，修权限即可，不触发本卡
- 仅 .git 创建被拒而同目录 touch 成功 → git 层残留（.git 文件、保护配置），非环境边界
- 会话 write-scope 回执已列出受限 pattern 且不含目标 → 边界已知且属会话配置，走 scope 变更申请，不必查 env
- 回执横幅已声明仅允许写工作区、且显式 workdir=目标 探针成功 → 属参数锚定型沙箱，按 workdir 重锚法继续；套用本卡的『宿主边界+转交』结论会误判
