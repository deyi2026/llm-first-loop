---
method_id: scoped-absence-claim-probe-ecosystem-location-classes-96aa29a92209
name: scoped-absence-claim-probe-ecosystem-location-classes
description: 空探针只证伪『被探测的那一个位置类』，不能支撑『本机/全工作区不存在』的绝对负断言。本集仅探测 IDE 扩展目录就断言『本机没有 WorkBuddy 插件』，而更早回执已显示该生态状态真实存放于 home 点目录/工具数据目录（live providers 候选含 ~/.cline/...、workspace 命中 .lfldata）；插件实际在 ~/.dsh/profiles/web/node_modules，靠一次查凭据的 env 检查才偶然撞见，被迫公开撤回，路线 B 的决定性证据（进程内 randomBytes secret、ported-from 注释）因此迟到。反模式：用单一窄位置类的空结果给全局存在性下结论。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:dbb11178-e3d2-4816-96e3-05377a07ca5b:284:3a613f0448d30a314b53
evidence_refs: learning:learn:73df1264aa37
created_at: 2026-10-13T19:10:47.916900+08:00
updated_at: 2026-10-13T19:10:47.916900+08:00
---
## Trigger
即将基于若干空回执对某 artifact（插件/配置/源码/凭据）作『本机或工作区不存在』的绝对负断言，且空探针只覆盖了单一位置类

## Discriminator
同一会话更早的回执已经展示过该生态真实存放状态的位置类（如 live providers 候选列出 ~/.cline/...、workspace 命中 .lfldata），而当前空探针的位置类与之不重合——knowledge-at-time 成立：此时只能输出限定范围的负结论，绝对负断言不成立

## Short path
- 未知量：该 artifact 是否存在于本机。先从已到手回执枚举『生态已演示的位置类』（home 点目录、工具数据目录、workspace 索引范围）
- 用一条 shell 探针按已证位置类通配（如对 ~ 下点目录做 *workbuddy* 级 glob），之后再下结论
- 命中：立即读取该 artifact 的清单/源码，把后续选型的承重事实建立在它上面
- 为空：才允许负断言，且措辞限定为『不在已探测的 X 类位置』

## Stop conditions
- 探针命中目标 artifact：转入读取其源码/清单，停止扩大探测
- 已证位置类全部覆盖且仍为空：输出带范围限定的负断言并停止

## Verification
- 对照早前回执逐类核对：每个已出现过的位置类都被至少一个探针 glob 覆盖
- 复核成稿措辞：负断言范围 ≤ 实际探测范围（『不在 IDE 扩展目录』而非『本机没有』）

## Counterexamples
- 包管理器索引是权威存在性来源时（pip list / npm ls 查包），单次权威查询的空结果即可下负结论，无需目录级排查
- artifact 只有一个规范安装路径（如 LaunchDaemon/site-packages）：直接探测该路径即可，home 级大扫除是浪费
- 问题是『是否在运行』而非『是否安装』：ps/lsof 的空结果本身就是答案，与位置类无关
- workspace 内 search 工具回执自带完备性声明（无匹配）时，workspace 范围的负结论可直接采信
