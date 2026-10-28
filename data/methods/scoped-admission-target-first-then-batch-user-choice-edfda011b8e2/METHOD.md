---
method_id: scoped-admission-target-first-then-batch-user-choice-edfda011b8e2
name: scoped-admission-target-first-then-batch-user-choice
description: 用户以极简指令授权不可逆对外发布但未指定目标，且环境中并存多个候选目标（平台后台）、已知缺陷的修复方式随目标互斥时：审查/准入闸的通过是 target-scoped 的，必须在过闸前先解决目标。做法：先完成全部与目标无关的工作（审查闸、修订、校验、产物 sha、错误披露），再把目标选择连同各目标分歧表、不可逆性与无回滚依据打包成单轮提问；获答复后才做目标差异化准备并携带 target 取准入。避免在目标未决时提前调用 scoped 准入（等 target_required 拒绝才补），也避免为已被 provenance 锁定的产物枚举 .releases 历史快照。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:8432bab4-9ec8-4407-a69c-0cd2c90dce64:1293:deed5852d8a5cb39e562
evidence_refs: learning:learn:20b702adf6ed
created_at: 2026-10-15T15:58:54.246291+08:00
updated_at: 2026-10-15T15:58:54.246291+08:00
---
## Trigger
极简指令授权不可逆发布（如「要审查和发表」）且未命名目标；浏览器/环境同时挂着多个候选发布目标；或 scoped 准入/审查闸工具的 scope 参数（target_name）尚无值

## Discriminator
准入工具 schema/拒绝回执已表明通过绑定具体 target（「未经检查的不同目标均无效」、publication_target_name_required）→ 不存在通用放行；候选目标对已知缺陷（如相对路径图片）要求互斥的不同处理；产物未被版本控制（无回滚）。任一在调用闸门前可见的事实都把『继续推进发布』缩成『先定目标』

## Short path
- 无活动 goal + 极简指令：按最近 edit/read provenance（evidence 时间线、带日期任务目录）锁定唯一待审产物，把 .releases/ 冻结快照排除出候选
- 按 SoT 审查规则跑闸：全量审查 → 修订 → 窄复审 PASS，登记产物 sha
- 调用 scoped 准入前检查其 scope 参数是否已决定：目标属用户授权域且未决 → 不调用该工具，转下一步
- 完成所有目标无关收尾（校验、错误披露、sha）后，单轮打包提问：目标清单 + 各目标分歧表 + 不可逆性/无回滚依据 + 已完成验证摘要
- 获答复后按目标差异化准备 → 携带 target 的 scoped 准入 → 执行发布 → 落回执并核对 target 一致

## Stop conditions
- 用户指令已点名目标，或仅存在单一可行目标 → 直接 scoped 准入并执行，不制造询问往返
- 目标无关工作已全部完成且提问已发出 → 停止翻查旧回执/重复检索，等待答复

## Verification
- 准入回执与发布记录中的 target 与用户答复及实际执行目标一致
- 提问发出前：审查闸 PASS、产物 sha 已登记、所有目标无关校验已通过

## Counterexamples
- 目标选择可逆或重做成本低（如本地导出多格式文件）→ 自行选择并汇报，不必打断用户
- 闸通过不绑定 target（通用 PASS）或动作本身可逆（保存草稿）→ 无需先定目标
- 用户已明确豁免询问或授权默认平台 → 按授权直接执行
