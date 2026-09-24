---
method_id: exact-id-lookup-in-system-of-record-before-semantic-search-c6a94d4ae9ad
name: exact-id-lookup-in-system-of-record-before-semantic-search
description: 用户转述带唯一 ID 的带外状态变更（如 web 面板审批）并明示本会话不会自动收到时，先用该 ID 对权威持久层（写入方落盘的 audit/状态文件）做精确查找，而不是对会话记忆做语义搜索。语义搜索干净未命中或超时本身就证明源类选错。命中记录自带的 content/impact_files 是直指待改 artifacts 的 provenance 边，可跳过对 venv/worktree 副本的文件名枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f88bda21-3714-409e-a903-eeb08b562780:331:f8a700f4063bb423ac12
evidence_refs: learning:learn:d2c5ff7961c3
created_at: 2026-09-23T09:19:59.438584+00:00
updated_at: 2026-09-23T09:19:59.438584+00:00
---
## Trigger
用户消息转述一次带外操作回执（另一通道已完成审批/状态翻转），含唯一 ID，并明确说明 AI 会话不会自动收到该事件，要求核实状态后继续执行

## Discriminator
回执写明了写入通道（web 面板）且明示会话不自动同步 → 权威状态在写入方的持久/审计层而非会话记忆；search_records 返回干净的『未找到』（success 回执、非 transient 失败）进一步证实该事件不在会话记录索引里

## Short path
- 从回执提取唯一 ID + 写入通道；未知量 = 该 ID 的权威当前状态；据此选定源类 = 该通道落盘的 audit/持久化文件，而非会话记忆搜索
- 对该层文件做精确 ID 匹配（布局未知时先一次 scoped find 于 data/audit）；读取 status 字段与 review log 行，交叉核对 ts/source 与回执一致
- 以命中记录自带的 content/impact_files 作为 provenance 边定位待改 artifact（经 import 图取 canonical 路径，跳过 venv/worktree 中的同名副本），按批准正文中的条目实施
- 运行批准记录中命名的验收标准/测试，将执行状态迁移写入 exec log；验收通过即停，不再向记忆/搜索层重复确认

## Stop conditions
- 权威记录已确认回执声称的状态（ID/时间戳/通道三者吻合）→ 停止核实，进入执行
- 批准正文中的验收标准全绿且执行已落盘登记 → 停止探索
- 持久层查无此 ID → 如实回报与回执不符，而不是换参数继续搜会话记忆

## Verification
- 回执中的 ID/时间戳/来源通道与权威 audit 行的字段逐一吻合
- 执行后状态迁移已写入执行日志；批准正文列出的验收用例/相关测试通过

## Counterexamples
- 回执本身已含权威确认，或当前工具状态查询已直接显示新状态 → 无需再核实，直接执行
- 查找目标是语义上下文或相关历史（为何被批、同类先例）而非单一 ID 的二元状态 → 语义 records 搜索才是合适工具，精确 ID grep 会漏
- 该系统的 system of record 是数据库/API 而非 JSONL 文件 → 精确查找应打到该处，不惯性 grep 文件
- 写入通道根本没有持久层或位置完全未知 → 此时一次有界的目录发现才是正确首步，本方法不适用
