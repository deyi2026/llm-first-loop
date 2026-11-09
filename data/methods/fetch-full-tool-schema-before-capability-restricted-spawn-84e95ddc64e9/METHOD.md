---
method_id: fetch-full-tool-schema-before-capability-restricted-spawn-84e95ddc64e9
name: fetch-full-tool-schema-before-capability-restricted-spawn
description: 首次用带嵌套能力参数的工具（如 spawn_subagent 的 requires：工具白名单/write_scope/network 声明）派发受限子代理（只读审查者）前，或首次因参数形状被拒后，不要凭记忆或按错误消息最小修补重试：形状类拒绝回执只列出合法字段，跨字段与行为约束（工具白名单为程序级强制、network 等能力声明缺口在 child 启动前拒绝、spawn 成功不等于任务完成）只写在工具完整 schema 里。先一条调用取全量 schema，按 schema 构造参数，把重试空间收敛为一次正确调用；纯读 child 无命令类工具时则无此跨字段负担。
aliases: 怎么派只读审查子代理, 子代理参数格式被拒怎么改, 子代理禁止写文件怎么配, 子代理能跑命令怎么声明能力, 派子代理前先看工具完整说明, 审查子代理权限收紧
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:89744d2b-208c-439c-a769-c6da9ba4abcd:0:7dc46138f61ca08a72d5
evidence_refs: learning:learn:493ab75be8e4
created_at: 2026-11-09T07:42:31.487561+08:00
updated_at: 2026-11-09T07:42:31.487561+08:00
---
## Trigger
需要以嵌套结构化能力参数（requires/write_scope/工具白名单）spawn 受限子代理（如只读 merge reviewer），而本会话尚未见过该工具的准确参数形状；或该类调用刚因参数形状被拒

## Discriminator
拒绝回执已列出 requires 全部合法字段形状但不含字段间约束；而工具全量 schema 可一条调用直接取得，其中明确写有『requires.network/fs/session_continuity 缺口在 child 启动前拒绝』『tools 声明即程序级强制白名单』『spawn 成功只代表已启动』等行为契约——只按错误消息修补大概率二次被拒，且 child 工具面配置无法从错误消息推知

## Short path
- 按闸 skill 指引先读 SKILL.md、确认证据文件在位与确切模型名（未知量：流程、证据、模型 id）
- 首次受限 spawn 前一条调用取 spawn_subagent 完整 schema（未知量：requires 精确形状与跨字段行为约束）
- 按 schema 构造 requires：tools=只读白名单、write_scope 空路径 deny、白名单含命令执行类工具则补 network 声明；一次 spawn 成功并核对回执 tool_scope 恰等于白名单
- 轮询至终态后，若 subagent_result 预览被截断，按 evidence ref 分段水合至 complete=true 再引用其逐条清单
- 落盘回执用守卫规定的先落盘再执行姿势；parent_session 等当前上下文标识用实时会话查询取值，绝不复制证据文件里的旧会话 id

## Stop conditions
- schema 已在本会话回执中完整出现且仍代表当前版本，即不再重取
- child 终态 completed/outcome=completed、报告水合 complete=true、回执 json-valid 落盘成功即停

## Verification
- spawn 回执的 tool_scope 与声明白名单逐项一致（程序级强制已生效）
- child 终态回执 child_state=completed/child_outcome=completed，verdict 与水合全文一致而非来自截断预览
- 回执中当前上下文字段（如 parent_session）等于本会话实时查询值；不得预写尚不存在的实测值（如合并后 main sha）

## Counterexamples
- 参数扁平且拒绝消息已含全部约束（如仅缺一个布尔字段）→ 直接机械补字段重发即可，取全量 schema 是浪费
- 子代理只需纯读工具（无命令执行类工具）→ 无 network 跨字段约束，最小 requires 即可成功
- 同一会话内该工具形状已被验证过（近期回执可查）→ 无需任何前置 schema 调用，直接复用已验证形状
