---
method_id: out-of-allowface-write-predict-deny-route-or-handoff-1dda33636b84
name: out-of-allowface-write-predict-deny-route-or-handoff
description: 沙箱回执头部已声明写允许面（如『仅允许写工作区与缓存目录』）时，对允许面外的固定路径（用户家目录下的仓库等）做删除/改写前，先用『目标路径 vs 可写根』的路径算术预判拒绝，不在沙箱内盲试 rm（本集产生 2969 行 Operation not permitted 噪声）；提权通道只管灾难性硬阻断，其回拒文本会指明沙箱模式边界归白名单/EXEC_MODE 通道。有 workdir 重锚就重锚后删；无任何可达通道就立即交接：已完成清单 + 用户一条精确命令。与 workdir 重锚卡互补：重锚是首选修复，交接是末路收尾。
aliases: 删不掉目录 Operation not permitted 沙箱, rm 被沙箱拦了怎么办, 沙箱外路径怎么删, 提权被拒沙箱边界, 让用户手动跑删除命令, 清理家目录仓库被拦
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:8c4a0f45-1c62-47b6-a42f-e75f6bb2027a:173:0dc9b76ca385998be8c3
evidence_refs: learning:learn:f68c1902c551
created_at: 2026-10-26T23:54:06.191087+08:00
updated_at: 2026-10-26T23:54:06.191087+08:00
---
## Trigger
收尾清理需删除/改写一个固定路径，而本轮每条工具回执头部已声明沙箱写允许面（『仅允许写工作区与缓存目录』类字样），目标路径疑似落在允许面之外。

## Discriminator
回执头部的允许面声明 + 目标路径前缀比对：目标不落在任何声明可写根之下 → 沙箱内写/删必被 Operation not permitted 拒；且早先回执 stderr（如 /bin/ps: Operation not permitted）已证明沙箱在主动执行拒绝，无需实测确认。

## Short path
- 先完成允许面内的清理：kill 前核 launchd/pm2/守护拉起向量（防复活），kill 后用 lsof 验证端口释放
- 动 rm/写之前做一次路径算术：目标是否落在回执声明的可写根内
- 落在面外且 harness 支持 workdir 重锚沙箱根 → 重锚后一次删除并以 ls -d 复验
- 无重锚/白名单通道时不在沙箱内尝试删除；提权通道只管灾难性硬阻断，回拒文本指明 EXEC_MODE/白名单归属后不再换措辞重试
- 输出交接收尾：已完成项清单 + 用户需执行的一条精确命令

## Stop conditions
- 允许面内目标全部达成并验证（进程已停、端口释放、注册表已清）
- 剩余目标确认在允许面外且唯一可达通道是用户本人 → 给出精确命令后停止，不再重试删除或提权

## Verification
- kill 后 lsof 确认端口不再监听
- 删除后 ls -d 目标路径：消失才算成功（本集 rm 后回显 STILL EXISTS，证明未删成）
- 通道归属以工具回拒文本为权威：『非灾难性硬阻断，请走 EXEC_MODE/白名单通道』即定案

## Counterexamples
- 目标路径在工作区/缓存目录内 → 直接删除，无需路径算术或交接
- 报错源于文件 flags（uchg/schg）或属主而非沙箱策略 → 路径算术不适用，先查 ls -lO 与属主
- harness 提供显式 workdir 重锚写法 → 先重锚一次再删并复验，用户交接是最后手段而非首选
