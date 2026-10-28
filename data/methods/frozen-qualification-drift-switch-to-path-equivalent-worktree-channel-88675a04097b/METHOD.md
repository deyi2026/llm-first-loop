---
method_id: frozen-qualification-drift-switch-to-path-equivalent-worktree-channel-88675a04097b
name: frozen-qualification-drift-switch-to-path-equivalent-worktree-channel
description: 冻结指纹的准入审查 PASS 后执行被拒（回执称不存在覆盖当前产物的有效资格，并行写者致 sha 漂移）时，不要在共享主树上反复竞速重试，也不要随手找干净 worktree 跑门：隔离（静态无漂移）与代表性（路径语义等价）是两个独立约束。先用最后写入 mtime+子代理拓扑判断写者节奏；用便宜 grep 确认门禁脚本能从 worktree 解析 venv/路径；再按已登记的路径敏感测试前提（如 TMPDIR=/tmp、allowlist 根、workspace 相对 glob）约束选址——worktree 必须避开 /tmp 等特殊根、放在仓库路径树内 gitignored 位置，使位置敏感判定不翻转。之后准入+全量在静态树上一次收口，红集应恰等于已登记环境红。
aliases: 准入PASS后执行被sha漂移拦截, 并行会话写树导致审查资格失效, 干净worktree跑全量门怎么选址, worktree放tmp测试红一片, 门禁资格竞态换静态通道, 路径敏感测试的worktree位置约束
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9982762e-d202-481b-9ca3-178124e943de:3028:cd9ef0e84f3214860a99
evidence_refs: learning:learn:6d426d482464
created_at: 2026-10-25T13:09:05.057016+08:00
updated_at: 2026-10-25T13:09:05.057016+08:00
---
## Trigger
sha/指纹冻结的准入审查已 PASS，但执行动作被拒（回执称不存在覆盖当前产物/目标的有效独立审查资格），且证据显示共享工作树存在并行写者持续变更

## Discriminator
两条当时已在手的事实：(1) 拦截回执明确把失效归因于资格与当前产物的 sha 不匹配（并发写者），而非门禁逻辑本身；(2) 本集开头检索已命中路径敏感测试前提的登记记录（沙箱 TMPDIR 重定向到 /tmp、guard 允许根含 /tmp 天然覆盖'workspace 外'构造）——任何把测试树挪进 /tmp 的隔离方案都会翻转这些判定

## Short path
- 资格被 sha 漂移拦截时，第一未知量=写者节奏：git status 差异计数+最近写入文件 mtime+子代理拓扑(active_children)，判断安静窗口是否可信；持续写者→尽早放弃主树竞速
- 便宜兼容性预检：grep 门禁脚本的 venv/cd/PY 解析段，确认 worktree 可用（回落主检出区 venv）
- 选址由已登记路径敏感前提约束：避开 /tmp 及任何 allowlist 特殊根，放仓库路径树内 gitignored 位置，保证位置判定不翻转
- 在静态 worktree 上走准入→全量门；预期红集=已登记环境红
- 红项对账 known_reds 台账+确认准入 sha 全程未变；通过即停

## Stop conditions
- 静态且路径等价的 worktree 中门禁终态出齐，红项均为已登记存量红、无未登记新红
- 或写者确认停笔且主树在单一安静窗口内完成资格+执行

## Verification
- 准入接受的 candidate_sha 与门禁完成时 sha 一致（无二次漂移）
- worktree 红集与 known_reds 登记逐条对账，无位置翻转产生的新红
- 门禁脚本在 worktree 下解析到正确解释器（预检输出确认）

## Counterexamples
- 测试套件无任何位置敏感前提（纯单元测试）→任意干净 worktree 位置皆可，选址约束多余
- 写者是本会话可控的后台任务→暂停/协调后在主树重跑更便宜，无需换通道
- 门禁脚本硬编码主检出区路径、不支持 worktree→需先改脚本，换通道不可行
- 准入不冻结指纹（无 sha 绑定）→资格漂移式失效不会发生，本方法触发条件不存在
