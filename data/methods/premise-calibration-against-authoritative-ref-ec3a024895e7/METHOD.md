---
method_id: premise-calibration-against-authoritative-ref-ec3a024895e7
name: premise-calibration-against-authoritative-ref
description: 当变更/文档任务的前提（哪一节旧了、缺什么机制）来自用户记忆或先前会话的旧读取时，先用一次廉价探针在权威 ref（实际服役的 commit/branch）上核对 artifact 真实状态，并找出过期副本的来源；把编辑范围从'按描述重写'收缩为'仅补实证残差缺口'。写入任何声称存在的机制（fence、存储推进、CLI 用法）前，先在目标 ref 的实现里读到该机制的确切代码与接口形状，锚点取自当前版本原文。这样避免按过期基线打补丁、避免文档化不存在的 fence，也避免按用户描述做冗余重写。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:010fcc8e-3ba8-4948-9ae5-66a30cc8ea6e:659:da525cc8665fc15cdda1
evidence_refs: learning:learn:a1e190c29b2e
created_at: 2026-09-17T15:11:18.544983+00:00
updated_at: 2026-09-17T15:11:18.544983+00:00
---
## Trigger
变更/文档任务附带对目标 artifact 状态的口头描述（如'S5 还是旧的'），且描述源自记忆或先前会话读取；同一 artifact 存在多副本/ref（服役线、worktree、另一根目录的未跟踪副本）。

## Discriminator
权威 ref 上一次探针的输出即可判别：目标文件在服役 ref 的行数/章节标题与描述不符（如 §5 已改名升级为控制面路径），且另一根目录存在未跟踪旧副本恰好解释了过期记忆，此时'按描述重写整个 §5'可缩为'只补 publish 推进段与陷阱警示'。

## Short path
- 确定权威 ref：变更必须落库的基线 commit/服役线；无法唯一确定则暂停询问，不猜测。
- 单次探针获取该 ref 上 artifact 的结构（章节/行数）+ 检查其他副本（未跟踪/worktree）是否解释过期记忆。
- 对照任务前提与真实状态，列出残差缺口；只对残差缺口设计改动，并把校准结果回报给用户。
- 对新文本将声称的每个机制，先在目标 ref 实现中读到证据（fence 代码、CAS 存储逻辑、CLI 子命令精确形状）再落笔。
- 锚点用当前版本原文打补丁，diff 验证内容；门禁若失败，先在干净基线双跑归因（一致即预存），再提交。

## Stop conditions
- 前提在权威 ref 上完全属实：直接按原范围编辑，不做额外探针。
- 权威 ref 无法唯一确定（多副本均可能服役）：暂停请用户裁决，不选边。
- 所有残差缺口已补齐、且新文本中每个机制声称都有实现证据：停止发现，进入验证与提交。

## Verification
- 补丁锚点全部匹配权威 ref 的当前内容，没有任何基于旧版上下文的改动。
- 新文本中每个 fence/机制/命令形状都能指向目标 ref 中读到的具体代码或 argparse 定义。
- 门禁失败输出与干净基线完全一致：归因为预存问题，与本次变更解耦后才提交。

## Counterexamples
- 目标是用户本地未跟踪草稿本身、无服役 ref：本地副本即权威，不要反向'校准'到仓库版本。
- 前提描述的是运行时行为缺陷而非 artifact 内容：读 ref 内容无法证实或证伪，需要运行时观测而非版本校准。
- 全新 artifact 无既有副本：没有前提可核对，直接创建。
- 用户明确 pin 死目标 ref 且其描述来自本会话实时观察：前提已新鲜，校准探针是多余开销，直接编辑。
