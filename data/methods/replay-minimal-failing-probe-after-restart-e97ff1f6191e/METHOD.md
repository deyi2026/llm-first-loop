---
method_id: replay-minimal-failing-probe-after-restart-e97ff1f6191e
name: replay-minimal-failing-probe-after-restart
description: 修复部署并重启后的回归验证：第一步就原样重放修复前的最小失败探针（本例 projection_kinds=["heading"]），让探针一次调用同时回答服务活性、页面在场与修复生效三个未知量；环境巡检（目录枚举、读 fixture 源码、tail 日志、pgrep）与人工翻页读取原始快照大文本，都降级为探针失败后的分支手段，而不是重启后的前置动作。每步只针对一个未知量：修复的失败签名是否翻转。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:1606:849104ca8a3294566c5d
evidence_refs: learning:learn:1803d4c1628c
created_at: 2026-09-18T06:32:33.581686+00:00
updated_at: 2026-09-18T06:32:33.581686+00:00
---
## Trigger
刚收到重启/部署回执 status=succeeded 且 deployment generation 已更新，同时手头已有修复前的最小失败复现（minimal repro）及其可观测失败签名，目标是对修复做重启后验证

## Discriminator
重启回执 succeeded（新 generation 已上线）+ 已知失败签名（projection_kinds=["heading"] 曾 matched_total=0，而 AX role=heading 就在页上）——这两条当时已存在的事实把'验证什么、怎么验证'缩成一次调用：原样重放该探针即可同时检验修复是否生效与页面/服务是否在场，无需先对 fixture 目录做 ls/grep/cat/pgrep 巡检，也无需翻页读全量快照原文去找目标对象

## Short path
- 读重启回执，确认 status=succeeded 且 generation 已更新 → 未知量：修复是否已上线
- 原样重放最小失败探针：带 projection_kinds=["heading"] 的 snapshot → 未知量：失败签名是否消失（期望 matched_total>=1 且目标对象 kind=heading）
- 探针通过即同时证明服务活着、页面在场、修复生效，直接进入写路径冒烟：投影 kinds=[button,input] 取 refs → click/fill → 用 diff/hydrate 验证效果内容
- 仅当探针返回空/报错/页面丢失时，才降级做环境检查（pgrep fixture server、读 server.py/log），把'修复失败'与'环境死亡'两种假设分开
- 效果断言（diff 新建节点文本、value_text）与预期一致后停止，汇总验证结论

## Stop conditions
- 原失败签名已被回执权威否定：重放探针 matched_total>=1 且目标对象 kind 与修复预期一致
- 写路径冒烟的动作回执 status=ok，且 diff/hydrate 的效果内容与预期一致（如 clicks=1、value_text 正确）
- 探针失败且环境检查定位到与修复无关的原因（fixture server 死亡、页面丢失）时，停止重复探针，先恢复环境再重放一次

## Verification
- 对比修复前同参数探针输出，确认失败→通过翻转（matched_total 0→>=1，kind generic→heading）
- 确认重放探针的调用参数与原始失败复现完全一致，避免验证了一个不同的东西
- 写路径用动作回执（before/after 版本、diff_ref）+ hydrate 内容双重确认效果，而非只看 status=ok

## Counterexamples
- 重启已知会杀死探针依赖的独立子进程（如 fixture server 不受该服务管理），且探针失败会在'修复坏了'与'环境死了'之间产生归因歧义时，先做一次轻量活性检查（pgrep/curl）是合理的
- 探针动作昂贵或有破坏性副作用（下单、删除、发消息）时，应先确认前置条件而不是盲发探针
- 探索型任务没有已存在的最小失败复现可重放，此时从宽感知/快照开始是正确起点，不适用本方法
- 被测对象就是原始输出层本身（如验证 evidence blob 的分页 range 语义）时，翻页读原文即探针，不算绕路
