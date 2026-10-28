---
method_id: probe-failing-process-falsify-permission-premise-before-remediation-db1d4dbd0b4c
name: probe-failing-process-falsify-permission-premise-before-remediation
description: 失败被归因为『缺权限』（或用户给出『花5分钟加授权』类修复建议）时，若同进程 status 回执已含矛盾信号——能力位可用而权限位 false——先把『失败进程是否真缺该前置』当唯一未知量：让失败进程自己执行一次同类最小操作（如对已知窗口做 snapshot）裁决。成功即前提证伪，停止授权与权限代码排查，转向对失败目标做两数据源逐字段 diff（窗口清单 vs AX 树），常能定位真实规则缺陷（如 bounds 逐字段相等、仅标题差，精确匹配误判未命中）。全新解释器探针是弱证据（权限主体可能不同），权限库读取与权限检查代码考古都不应先于这一次探测。
aliases: 用户让加权限先别急着加, 权限位false但能力位true, 拿失败进程自己探一次再说, 新进程探到的权限不算数, 窗口绑定失败先比标题和bounds, 授权前先证伪权限前提
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:36553398-1c59-4c05-927f-23e13f8396e6:2069:9c22a5275d4e158c4704
evidence_refs: learning:learn:0ccaa2979679
created_at: 2026-10-28T09:57:05.740863+08:00
updated_at: 2026-10-28T09:57:05.740863+08:00
---
## Trigger
长驻服务进程的某操作失败，被用户或错误码归因为缺权限/缺环境前置，且已持有的同进程 status 回执出现内在矛盾：能力位（如 can_read_ax）为 true、error 为 null，而权限位为 false；或用户直接给出低成本的修复建议（加授权/装依赖）作为前提

## Discriminator
回执内已有矛盾事实：能力三 bit 全 true 且 ax_error=null，与权限位 false 并存。该矛盾在第一次 status 时就已可见，足以把『缺权限』从结论降级为待证假设，且一次同进程同类最小操作即可裁决；无需授权操作、无需读权限数据库、无需 grep 权限检查代码

## Short path
- 读失败进程的 status 回执，登记能力位 vs 权限位的矛盾；定义唯一未知量：失败进程是否真缺该前置
- 用失败进程自身执行一次同类最小操作（对已知窗口 snapshot）：成功→权限前提证伪，立即停止授权/权限库/权限代码排查
- 前提证伪后转向下一未知量：为何特定目标失败——对失败目标做两数据源逐字段 diff（窗口清单的 title/bounds vs AX 树的 title/bounds）
- diff 定位差异字段（bounds 相等、标题仅后缀差）→ 把匹配规则修为分级（exact>relaxed>bounds_only）并带 degraded 标记，不静默降级
- 全量单测 + 新进程 E2E 验证绑定依据后停止

## Stop conditions
- 失败进程的同类最小操作成功：权限前提已证伪，不再授权、不读权限库、不翻权限检查代码
- 逐字段 diff 找到差异字段并修为分级匹配，测试与 E2E 通过：归因闭合
- 若探测返回权限专属错误码（如 ax_unavailable）：前提成立，转授权路径

## Verification
- 确认裁决探针与失败发生在同一进程（比对 pid），不是全新解释器跑的结果
- 确认修复后规则对原失败目标显式给出绑定依据（如 title_relaxed+degraded 标记），多命中仍拒绝
- 把权限位口径写进文档：原始位 vs 探针为准，且把『权限缺失』与『匹配规则错』两种失败原因分开记载

## Counterexamples
- 回执权限位与能力位同向（都 false）且失败操作报权限专属错误码：前提成立，直接走授权路径，不要继续探测
- 失败进程无法执行任何同类探测（工具面不暴露该操作）：同 binary 新进程探针是合法的弱证据代理，此时不得因『新进程不算数』而拒绝一切探测
- 探测会触发有副作用的系统交互弹窗且用户不在场：先读该权限位语义的代码/文档注释更便宜，不必强行探测
