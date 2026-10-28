---
method_id: diagnose-failed-managed-action-via-id-keyed-record-not-snapshot-paging-1648d9a77e6f
name: diagnose-failed-managed-action-via-id-keyed-record-not-snapshot-paging
description: 状态回执已给出 action_id 且显示 failed（或与上游报告宣称的状态矛盾）时，失败原因的权威位置是按 id 命名的 action 台账记录及其专属日志（记录 detail 字段通常自带 log=路径指针），而不是分页翻读聚合 runtime snapshot。聚合快照首个读取段若被审计遥测（generation_lag/准入信号清单）占满，这本身就是『答案不在这里』的噪音签名，应立即放弃换 offset 续读。一次 find by id 前缀 + 读记录 JSON + tail 其指向的日志即可拿到 rc 与根因，再按根因最小修复并重发、记录新 action_id。同时避免先绕 CLI 包装面：既可能踩管道直连解释器的安全硬阻断，又有缺参 usage 往返，且 CLI show 多半只给部署元数据而非失败原因。本卡只管诊断路由；身份门/worktree 转挂等具体修复语义由对应既有发布前检卡覆盖。
aliases: 重启失败先找按id命名的回执文件, 别翻运行时快照找action明细, 快照全是lag遥测噪音, 托管服务failed从哪查原因, 回执detail里的log路径直接tail, 报告说在等待实测已失败
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9982762e-d202-481b-9ca3-178124e943de:4439:b5b067830a8cf2445fe4
evidence_refs: learning:learn:47ea2894cde9
created_at: 2026-10-26T10:42:59.318746+08:00
updated_at: 2026-10-26T10:42:59.318746+08:00
---
## Trigger
托管/异步动作（发布、重启、部署类）的状态回执显示 failed、或与上游报告宣称的状态（如『仍在等待』）矛盾，且回执已打印 action_id，需要定位失败原因时

## Discriminator
两条当时已知事实可收窄搜索：①状态回执已给出 action_id 与 desired/live 偏差；②聚合 runtime snapshot 的首个分段几乎全是审计遥测（lag/准入清单）而非 action 明细——这是聚合体不含答案的噪音签名。按 id 命名的 per-action 台账文件与专属日志可直接寻址，且记录 detail 自带 log= 指针形成现成 provenance 边。

## Short path
- 用一次状态查询核对报告宣称的状态（如 waiting）→ 拿到 action_id 与 failed 事实；未知量：报告是否属实
- 持 action_id 做 find/-name 前缀匹配，定位 id 命名的 action 记录 JSON 与专属日志文件；未知量：失败原因在哪、是什么
- 读记录 JSON + tail 其 detail 指向的日志 → 取得退出码与根因；未知量：机理是门正常工作还是缺陷（必要时用一条 git 身份比对验证）
- 按根因做最小修复并重发动作，记录新 action_id 与绑定校验，停止——不回头再翻聚合快照

## Stop conditions
- action 记录与其日志已给出确定性退出码/根因，且与状态回执相互印证
- 修复动作已被受理（新 action_id）且 desired 绑定（generation/head/产物指纹）校验通过

## Verification
- 记录中的 deployment_id/generation 与状态回执 desired 一致
- 日志尾部 rc 与记录 detail 字段相互印证
- 重发后新动作被受理，live 收敛留待下一窗口用状态查询核验

## Counterexamples
- 系统不存在按 id 命名的 per-action 台账，只有聚合快照 → 必须在快照内做结构化/分段检索，本卡路由不可用
- 未知量本身就是聚合层面的问题（如各部署 lag 分布、准入信号盘点）→ 应读聚合遥测而非单条 action 记录
- action 记录滞后于真实进程状态（worker 尚未写终态）→ 以日志尾部/进程证据为准，不能单信台账记录
- 只有 CLI 封面可用且无数据目录读权限 → 按 usage 回执补齐参数走 CLI 是正当路径，不算绕路
