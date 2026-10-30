---
method_id: sandbox-git-timeout-split-to-minimal-exact-ref-probes-23da5fb1aad0
name: sandbox-git-timeout-split-to-minimal-exact-ref-probes
description: 沙箱 shell（有秒级超时上限）里询查共享/大工作区仓库的 git 事实时，组合命令（管道+fetch/status 等）超时后不要原形态重试：超时回执=组件归因失败而非逻辑错误。把询查压成每个未知量一条有界 exact-ref 单条命令（git log -1 <ref>、rev-parse --verify），剔除三类挂起面：读 stdin 的管道组件、网络子命令、全树扫描。『远端是否被推进』在全部写入方都在本地仓库时用本地 remote-tracking ref 作代理并声明局限；关键结论只挂 ref 值/直接回执，提交信息里的自述状态只算线索。
aliases: git 命令 60 秒超时怎么拆, 命令挂住先拆成最小单条再跑, 不 fetch 怎么确认推没推, 沙箱里 git status 扫大仓库会卡, git 管道组件读 stdin 挂死, 超时回执不是报错是没法归因
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6e7b4358-a1b8-4e23-a99c-931d6e86bee2:781:0065767da8cba20a67fd
evidence_refs: learning:learn:43a37989a8b4
created_at: 2026-10-30T22:50:18.909913+08:00
updated_at: 2026-10-30T22:50:18.909913+08:00
---
## Trigger
在带超时上限（如 60s）的沙箱 shell 中对共享/大工作区仓库询查 git 事实（远端是否推进、本地积压、某提交是否存活、并发会话是否活跃），命令含管道/网络子命令/全树扫描成分，或已收到一次『超过 Ns 未完成』回执。

## Discriminator
超时回执是组件归因失败而非命令逻辑错：组合命令无法定位哪个成分在挂；而 exact-ref 单条读（log -1 <ref>、rev-parse --verify <sha>^{commit}）只走对象库/引用、有界、成败可归因。环境侧证据（沙箱横幅、本会话早前 EPERM/作用域不匹配实测）已提示命令行为受约束，应从第一条命令起就压低复杂度。

## Short path
- 先从既有状态快照列出结论所需最小未知量清单，每个未知量配一条可独立验证的查询
- 收到首次超时即停止以组合形态重试，拆成一次只回答一个未知量的最小单条命令
- 剔除三类挂起面：管道里空参会读 stdin 的组件（如 ls-tree）、fetch/ls-remote 等网络子命令、git status 等全树扫描
- 『远端是否被推进』在网络命令不可用时，若全部写入方都在本地仓库，用本地 remote-tracking ref 作代理并显式声明其局限
- ref 值/直接回执覆盖全部未知量后立即停止，不再补查同源事实

## Stop conditions
- 每个未知量都已由 ref 值或直接回执单独回答
- 最小单条命令仍超时：判定为环境/IO 层问题而非命令形态问题，换时间窗或声明该询查当前不可达

## Verification
- 关键结论只落在 ref 值与工具回执上；提交信息里的自述状态（如『审查 PASS』）标注为线索而非既证事实
- 复合结论拆分量核验：『push 未发生』挂 origin tip 不变，『属主活跃』挂最新提交时间戳，两出处相互独立

## Counterexamples
- 远端可能被其他机器/协作者推进时，本地 remote-tracking ref 只是陈旧缓存，代理结论不成立，必须 ls-remote 或明示未核
- 无沙箱小仓库、命令毫秒级返回时组合命令没有挂起面，逐条拆分是纯开销
- 超时由瞬时负载或 IO 争用造成、最小单条同样挂起时，拆分无效，应改换执行时机或询查通道
