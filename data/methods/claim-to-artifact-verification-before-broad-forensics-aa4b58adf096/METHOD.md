---
method_id: claim-to-artifact-verification-before-broad-forensics-aa4b58adf096
name: claim-to-artifact-verification-before-broad-forensics
description: Map each narrative claim to its already-named artifact before broad forensics. Order: current-state claims first via one authoritative status read (gates urgency: still broken?); timeline claims via mtime-ordered listing of named runtime dirs plus a time-window-restricted find (mtimes reveal omitted events like a third-party clear); mechanism claims by reading the exact named code branch (design markers may overturn 'missing code' stories); historical/config claims against named commit/env keys. Broad discovery only for claims lacking identifiers.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fc0ed66c-e669-41c4-94d7-7e05031bbac6:4:35e7a8a531285164a660
evidence_refs: learning:learn:54d35b6c3a4f
created_at: 2026-09-22T17:21:12.640337+00:00
updated_at: 2026-09-22T17:21:12.640337+00:00
---
## Trigger
用户提交一份内嵌具体标识符（操作/动作 ID、文件路径、commit hash、配置键、时间戳）的事件因果链叙述，并期待核验或修复决策

## Discriminator
叙述中的每条声明是否都已命名或隐含一个具体 artifact（状态快照、回执 JSON、屏障目录、代码分支、env 键、commit）。标识符齐全时，核验是确定性的 claim→artifact 查找；只有某条声明找不到标识符才是扩大搜索的信号

## Short path
- 把叙述声明分类为：当前状态/时间线/机制/修复建议，并为每条列出其已命名的 artifact
- 用一个权威状态读取核验当前状态声明（是否仍在故障？决定紧迫性与是否还需止血）
- 对已命名的 runtime 目录做 mtime 排序列表，并把 find 限定在声明的时间窗口内——mtime 增量会暴露叙述遗漏的事件（如第三方清除）
- 读取叙述点名的确切代码分支（如 rc≠0 处理）核验机制声明——设计性注释/显式策略可能推翻『缺代码』的定性
- 对历史/配置声明直接查点名的 commit 与 env 键
- 逐条给出 确认/修正/时间线缺环 判定后，才起草修复项

## Stop conditions
- 所有叙述声明都有引用具体 artifact 的判定（确认/修正/缺失），无未映射声明
- 某声明无标识符或其 artifact 已消失——仅对该条扩大到发现式搜索
- 根因定性已对照实际代码分支核实后，才进入修复起草

## Verification
- 每个判定引用 path+内容 或 path+mtime，而非叙述转述
- 任何『还横在通路上』类当前状态声明都对照 live 状态复核，不沿用叙述假设
- 代码行为声明引用真实分支/注释原文（如显式 keep-on-failure 策略）后才接受或反驳
- 时间线包含 mtime 增量揭示而叙述未提的事件

## Counterexamples
- 叙述只给症状、无任何标识符——无法做 artifact 映射，宽发现才是正确首步
- artifact 的 mtime 不可信（从备份恢复/拷贝而来）——mtime 增量时间线推理失效，应改用日志/回执
- live 进程可能运行与所读源码树不同的 commit——先把进程 git head 对齐后才可把源码当运行时证据
- 用户已核验过状态、只要设计讨论——重复核验不产生新信息
