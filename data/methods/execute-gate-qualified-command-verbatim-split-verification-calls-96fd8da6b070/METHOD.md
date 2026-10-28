---
method_id: execute-gate-qualified-command-verbatim-split-verification-calls-96fd8da6b070
name: execute-gate-qualified-command-verbatim-split-verification-calls
description: 受保护 shell 动作（push/publish 等对外副作用命令）的审查资格绑定到逐字命令串：受理回执 target 含 command 哈希与冻结源 commit。执行时必须原样单命令重放；任何追加（&& 拼核验、复合命令）都会使实际命令与冻结 target 不再逐字一致，触发确定性绑定拒绝（如 compound_protected_shell_requires_split_commands），只能拆分后原样重试。远端 SHA 核验、状态列表等辅助操作一律作为独立调用，放在受保护动作前后单独执行。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:54ba6da3-7041-4b6f-8aac-8df1e542850f:241:aacf41da2ee565db0867
evidence_refs: learning:learn:4d1e3b87798d
created_at: 2026-10-22T21:27:51.898895+08:00
updated_at: 2026-10-22T21:27:51.898895+08:00
---
## Trigger
审查/门禁回执把资格审查绑定到精确命令串（target 含 command hash）+ 冻结 commit，且该动作属受保护 shell 准入；执行阶段同时想顺带做核验、列表等辅助操作

## Discriminator
受理回执形如 target=动作类型:产物hash:command:hash 且冻结 push_src_commit；同会话早前链路以逐字单命令重放即被放行——执行前即可判定：对命令的任何扩展都会破坏绑定，辅助核验必须外置为独立调用

## Short path
- PASS 到手后，将待执行命令与冻结 target 对应命令串（或接力指令中的 cmd）逐字比对：remote、分支、参数完全一致
- 以逐字一致的单命令作为独立调用执行受保护动作
- 远端 SHA/落盘核验作为下一个独立调用执行，绝不与受保护命令用 && 或分号拼接
- 若被 compound…requires_split 类拒绝：不重发审查，直接拆分——受保护部分原样重放，辅助部分另行调用

## Stop conditions
- 受保护动作以逐字命令独立执行且回执成功
- 独立核验确认远端/落盘 SHA 与审查冻结值一致，链路闭环
- 拒绝原因为策略/资格类而非命令绑定类时，停止拆分重试，转入对应处理

## Verification
- 执行后用独立调用核验远端 SHA == 审查冻结 push_src_commit
- 确认实际执行串与冻结 target 的 command hash 覆盖串逐字一致
- 回执台账中受保护调用与核验调用是两个独立条目

## Counterexamples
- 资格审查按 artifact/内容哈希（文档、产物）而非命令串绑定时，发布调用与其它步骤合并不一定破坏绑定——按内容身份而非命令逐字判断
- 不受保护的只读/信息命令（status --porcelain、ls、cat）可自由复合，强行拆分只增加轮次
- 门禁本身以复合命令为 target 且支持子命令绑定的环境，逐字重放原复合命令即可——规则是'与冻结 target 逐字一致'而非绝对禁止复合
