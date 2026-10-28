---
method_id: vary-workdir-param-not-target-path-on-sandbox-write-denial-b7a812a141b4
name: vary-workdir-param-not-target-path-on-sandbox-write-denial
description: 沙箱化 shell 工具的可写白名单绑定在工具调用的 workdir/workspace 参数上，命令内 `cd 目标目录` 不会扩展它。当对目标目录的写返回 Operation not permitted、而每条回执横幅声明『仅允许写工作区与缓存目录』、或快照读取报 WorkspaceScopeMismatch 时，第一未知量是『该沙箱的可写范围由什么定义』：用一次显式传 workdir=目标目录 的最小 touch 探针判别，可写即原地备份+修改+diff 验证；不要枚举各目录找碰巧可写位置再走复制→编辑→cp 回写链（第三方工具如 patch 还会因系统 TMPDIR 被禁而失败）。本集此误区消耗约 6 次跨目录写探测后才被 workdir 探针一发解开。
aliases: cd 了还是写不进去沙箱, 说允许写工作区却 Operation not permitted, workdir 才是沙箱白名单, snapshot 报 WorkspaceScopeMismatch 还能怎么写文件, 沙箱写被拒先换 workdir 探针, 写不进目标目录别急着找别的可写路径
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:6e7b4358-a1b8-4e23-a99c-931d6e86bee2:345:2133516e835e99a110f3
evidence_refs: learning:learn:334757afbb44
created_at: 2026-10-28T10:44:08.219318+08:00
updated_at: 2026-10-28T10:44:08.219318+08:00
---
## Trigger
沙箱化命令工具（回执横幅声明仅允许写工作区/缓存目录）中，`cd 目标目录 && 写` 返回 Operation not permitted，或 read_file(snapshot) 报 WorkspaceScopeMismatch，而任务要求修改该目录内的文件

## Discriminator
回执横幅把可写范围命名为『工作区』——该范围由工具调用的 workdir/workspace 参数在启动时声明，命令内 cd 不改变它；且写探针出现反常（无关仓库可写、任务自己的工作区反不可写），证明白名单不是固定路径特权表而是跟随每次调用的 workdir 绑定。首个失败已把未知量指到『范围由什么定义』，一次单变量探针即可回答

## Short path
- 首个写拒绝出现时，把未知量定为『本沙箱可写范围由什么定义』，而非『哪些路径碰巧可写』
- 单变量实验：execute_command 显式传 workdir=目标目录，执行 touch .wtest && rm .wtest，与不传 workdir 的 `cd P && touch` 版本对照
- 可写 → 确认范围绑定 workdir；原地完成写入（先 cp 备份再改），不走 /tmp staging+复制回写链，也不用会碰系统 TMPDIR 的 patch 等工具
- 落盘后 diff(备份, 现文件) 应为单点增量，sha256 前后对账，停止

## Stop conditions
- workdir=目标目录 探针可写且写入成功，diff 验证仅含预期改动
- workdir=目标目录 仍被拒 → 属真实路径级限制，切换到 staging/复制链或提权申请，不再重复 workdir 假设

## Verification
- 探针对照：同一路径，无 workdir 的 `cd P && touch` 失败 vs workdir=P 的 touch 成功，先确认绑定关系再写
- 写后 diff 备份与现文件应为单点增量；前后 sha256 对账

## Counterexamples
- 工具没有 workdir/workspace 参数（普通本地 shell）：范围绑定假设不成立，路径探测与复制链仍是正当手段
- 目标目录本身只读或受系统保护（SIP、只读卷）：workdir 无法解锁，失败与范围声明无关
- 文件已在当前声明工作区内但写仍失败（属主/权限位/文件锁）：变量是文件权限而非范围绑定
- 一条命令需同时写多个分散目录：单 workdir 绑定不适用，应按目录拆分调用而非硬套
