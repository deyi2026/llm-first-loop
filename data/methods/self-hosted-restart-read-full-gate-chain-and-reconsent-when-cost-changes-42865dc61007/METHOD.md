---
method_id: self-hosted-restart-read-full-gate-chain-and-reconsent-when-cost-changes-42865dc61007
name: self-hosted-restart-read-full-gate-chain-and-reconsent-when-cost-changes
description: 受控重启/变更生效动作的目标是承载当前会话的服务（本对话就跑在该进程里）时，status 里挂起的等待门只是条件链前段：逐门 override 成功不证明终态可达——物理阶段可能还有独立的 fail-closed 前置（如 precheck:active_run），且通过它的唯一通道可能硬切本会话。正确顺序：先从失败回执钉死阻塞者=本会话自身；再读 worker/物理脚本枚举 accepted→物理完成的全部门禁与 fail-closed 项；若唯一通道带有原授权未涵盖的用户可感知代价，视为旧授权失效，呈报差分重新确认；确认后按当前代发起、逐门 override（含 precheck 级门）、一次终态核对收束，不做盲轮询；对用户描述的完成机制必须有脚本行为或实测支持，被证伪立即收回更正。
aliases: 重启会把自己对话断掉怎么办, 门禁都override了还是failed, 服务一直busy重启超时收不了尾, 先读重启worker脚本再承诺结果, 授权之后执行代价变了还要再问吗, 自己会话占着run lock重启不动
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e827e946-e151-4ded-9bdf-58c042570992:184:66deb1861d6d33e9d156
evidence_refs: learning:learn:41e64f90e4e3
created_at: 2026-10-30T21:20:16.381732+08:00
updated_at: 2026-10-30T21:20:16.381732+08:00
---
## Trigger
从被当前会话托管的服务内部发起对该服务的受控重启/变更生效动作，且控制面对挂起门禁提供 override 出口；已有动作因『active run locks=本会话』类原因 failed，或回执显示等待门以 requester 会话退出为条件

## Discriminator
失败/受理回执与 schema 同时给出两条当时已知事实：①阻塞者身份=请求方自身（active run locks:1 且 requester_session_id=本会话，只要本对话活着就持续 busy）；②动作由 detached worker 分阶段执行、存在带自身复核的物理阶段。⇒『当前挂起门全部 override 成功』≠『终态可达』：物理阶段可有独立的 fail-closed 前置，其 override 是另一个命名门，在 status 挂起列表里根本看不到；完整条件集只能在 worker 脚本/日志中枚举。

## Short path
- 用首个失败回执一次性钉死阻塞者身份=本会话自身（detail 已给 active run locks 与 session id），不再用轮询或新动作去'确认 busy'
- 在向用户承诺任何完成路径之前，读一次 worker/物理阶段脚本（或已有 worker 日志），枚举 accepted→物理完成的全部门禁、超时与 fail-closed 项——特别是 override 挂起门覆盖不到的前置
- 若枚举发现唯一可行通道带有原授权未涵盖的用户可感知代价（如硬切当前对话页面闪断），把差分如实呈报用户取明确确认；不把『可以重启了』的旧授权直接套到新代价路径上
- 确认后按当前 generation 发起动作（代数漂移则先做 344⊇343 式包含性核验），逐门 override（含 precheck 级门），以一次终态核对收束，不做长程盲轮询

## Stop conditions
- 用户明确接受新代价并确认，且一次终态核对（status/事件流/worker 日志）给出 succeeded
- 用户拒绝 → 保持现状，如实汇报残留影响面（哪些目标已生效、哪个未生效）
- 枚举发现某门禁无 override 出口（硬安全/身份边界）→ 转外部执行者或人工通道，本会话内不再重试或轮询

## Verification
- override accepted 不等于完成；终态只认 status/事件流/worker 日志的 succeeded/failed，未查询到终态不得宣布结果
- 对用户说出的『会话关闭后自动生效』类机制承诺，必须先有 worker 脚本行为或实测证据支持才可出口
- 已对用户承诺的机制被实测证伪时，立即收回并如实更正（本集此做法正确，保留）

## Counterexamples
- 重启目标不托管当前会话（如从 web 会话重启 feishu/learning）：阻塞者非自身，有界等待后复查一次即可，无需读全链或重新授权
- 控制面明确无物理阶段额外前置的简单动作：override 完挂起门后短程有界轮询即可，读全链属过度动作
- 用户授权时已明确包含中断代价（『就算断我页面也重启』）：无需再次确认，直接沿全链推进
- 门禁是无 override 出口的硬边界：枚举结论应是移交外部执行者，而非在本会话内继续 override 推进
