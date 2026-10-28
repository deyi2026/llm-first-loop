---
method_id: relay-snapshot-anchor-index-before-rediscovery-404263299aaa
name: relay-snapshot-anchor-index-before-rediscovery
description: 接手跨会话接力快照时，把快照当锚点索引用，而不是当散文读完再重新做发现。快照里引用的路径（分支@deploy目录）、commit、服务/记录 ID、文档名本身就是发现地图兼核验清单：先读运行态回执一次拿到服务与 live git 终态（快照 checkpoint 可能已落后，以回执 delta 为准）；git 核验直接在快照点名路径上 -C 定点执行，不要在父目录试错后枚举 home；外部状态翻转按 ID 查登记簿记录。当全部决策相关未知量已被权威记录闭合后即停，『已写入新会话』的叙述性交接文本不是新未知量，其内容可由已核验事实+需求文档重建，不要为它连换多种检索策略。
aliases: 接手接力快照先挖锚点再动手, 交接快照里的路径和commit直接用别重找, 新会话核验上一会话遗留副作用, 快照checkpoint落后于实际状态, 找不到交接建议文档就停, 长会话收尾接管核验清单
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:dde2bfc3-0cb0-4295-beeb-ebfc5ea079d2:0:b444e7487b89c9587712
evidence_refs: learning:learn:9adc3f0fc640
created_at: 2026-10-26T12:28:54.103124+08:00
updated_at: 2026-10-26T12:28:54.103124+08:00
---
## Trigger
接手跨会话接力/交接快照（长会话收尾产物），被要求核验来源会话外部副作用终态并继续任务；快照正文中已出现具名锚点（路径、commit、分支@目录、服务/记录 ID、文档名）

## Discriminator
行动前每个待核验未知量已有具名权威位置：快照引用的代码根相对路径+commit（如 分支@deploy/xxx + live git 回执）、按对象 ID 可查的登记簿记录、Goal 点名的需求文档路径；此外『已写入交接文档与新会话』这类声明说明叙述性内容已随快照送达——独立文件缺失不构成新未知量

## Short path
- 从快照提取锚点清单：每个核验目标（服务终态、evolution 收口、代码根一致性）对应一个具名权威位置
- 先读运行态/任务回执，一次取得服务、restart、live git 终态；与 checkpoint 对照并显式报告 delta（快照可能滞后于实际）
- git 一致性在快照点名路径上定点执行（git -C <quoted deploy dir>），比对 HEAD 与 live git；已批准的副作用在原位实测交叉验证（如 exclude/check-ignore）
- 外部状态翻转按对象 ID 直查对应登记簿记录（kind=evolution_exec），与回执状态一致即闭合
- 读快照/Goal 点名的需求文档，取得后续任务验收口径与依赖顺序
- 汇报已闭合项、delta、待用户决策项后停止；不为已由权威记录覆盖的叙述性工件再发起多策略检索

## Stop conditions
- 快照遗留的全部核验目标均由权威记录或原位定点实测确认终态（含与 checkpoint 的差异说明）
- 下一步行动的阻塞点已定位为明确的用户决策/授权项
- 叙述性交接文本未单独落盘但决策内容已被权威记录+需求文档覆盖——此缺失不触发新检索

## Verification
- 每个结论可指向一条权威回执/登记记录/定点命令输出，而非快照转述
- 代码根 HEAD = 服务 live git = 登记记录中的 commit，三方一致
- 以运行态回执为准修正快照 checkpoint，并在汇报中显式列出 delta

## Counterexamples
- 快照是纯叙述、无任何具名锚点（无路径/ID/commit）→ 锚点驱动不适用，需从任务库与目录层做正常发现
- 点名锚点已过期（后续迁移/重构更换了 deploy 目录或工作区已外移），定点命令 ENOENT/404 → 此时升级到目录级枚举是正确动作，不算违反本方法
- 用户交付物就是『逐字拿到上一会话的建议原文』→ 定位交接文档本身成为任务未知量，应改走生成器定位（读生成工具源码确定输出目录），不能以已覆盖为由跳过
