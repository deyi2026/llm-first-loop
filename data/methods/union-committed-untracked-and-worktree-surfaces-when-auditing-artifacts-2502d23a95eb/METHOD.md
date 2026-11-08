---
method_id: union-committed-untracked-and-worktree-surfaces-when-auditing-artifacts-2502d23a95eb
name: union-committed-untracked-and-worktree-surfaces-when-auditing-artifacts
description: 用户要求按时间窗罗列/盘点工作产物（如"今天的设计 MD"）并裁决其是否已实施时，任何单一发现面都会系统性漏检：docs 索引 miss 且其参考列表全是窗口外旧题＝索引不覆盖未提交产物；git log 只见已提交；实施可能藏在隔离 worktree 而主工作区显示干净。正确做法是取并集：goal/coordination 台账拿会话归属与阶段状态，git log --since + status --porcelain + 产物目录 mtime 扫描合成产物清单，实施裁决再扩展到 worktree list 与各 worktree 的 main..HEAD。本集两条设计文档一条未跟踪未实施、一条实施半途困在 worktree 未合入，均靠多面并集才凑全。
aliases: 查今天哪些只出了文档还没动代码, 盘点没落地的产出, 设计文档实施到哪一步了, 有没有文件根本没进git, 工作区干净就等于没实施吗
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:0:c80bf81f1da8507bc9d4
evidence_refs: learning:learn:1769c913e5cd
created_at: 2026-11-07T23:20:04.721836+08:00
updated_at: 2026-11-07T23:20:04.721836+08:00
---
## Trigger
用户按时间窗盘点/罗列某类工作产物（文档/设计/代码）并要求判断其下游状态（是否已实施、已提交）；或产物检索在 docs 索引面 miss 且其"最近文档参考"列表不含窗口内条目。

## Discriminator
单一面的不全信号在早期即可见：docs 检索 miss 且参考列表全是窗口外旧标题＝索引不覆盖未提交产物；窗口内 git 提交数明显少于活跃 goal/会话的产出量；goal checkpoint 文本出现"未提交/隔离 worktree"字样；git log 回执自带未提交 ?? 段。任一命中即判定必须多面取并集，而不是换词重搜同一索引。

## Short path
- 先取 coordination/goal 台账：窗口内活跃 goal 的产物路径、会话归属、阶段与提交状态——用它做产物发现与归属，替代 raw 事件流宽枚举
- 定位仓库后一次合并查：git log --since=<T>（已提交）＋ git status --porcelain（未提交/未跟踪）＋ find <产物目录> -newermt <T>（mtime 兜底），三面并集为产物清单
- 逐份读产物自声明状态头（草案/未实现/版本号）作为实施初判
- 实施裁决扩展到 git worktree list ＋ 各隔离 worktree 的 log main..HEAD 与 porcelain：主工作区干净 ≠ 未实施
- 每份产物给出（产出证据，实施证据）二元组，均具名到 commit id / ?? 状态 / worktree 路径后停止

## Stop conditions
- 产物清单已由 ≥2 个独立面（提交历史/porcelain/mtime/goal 台账）交叉印证，且每份产物的实施结论都有具名 surface 支撑
- 用户明确只要已提交/已发布产物时，收敛为单面（git log / release 面）即停

## Verification
- 复核产物清单＝提交历史 ∪ 未跟踪 ∪ mtime 三面并集，逐一确认无单源遗漏（本集第二份设计文档仅存在于未跟踪面，单查 git log 会整份漏掉）
- 每条"未实施"结论能指出已检查过的全部实施面：main src diff、全部 worktree 的分支提交、任务图/goal checkpoint 状态

## Counterexamples
- 单 worktree、即写即提交的小仓库：git log --since 已完备，附加扫描是纯开销
- 产物目录混有大量生成/缓存文件：mtime 扫描噪声淹没信号，应改用 porcelain＋goal 台账
- 用户问的是产物内容（设计里写了什么）而非盘点：直接读文档，不做多面枚举
