---
method_id: same-head-falsifies-new-code-rescue-attribution-a7644c47f684
name: same-head-falsifies-new-code-rescue-attribution
description: 提交事故复盘/演进建议等把『恢复成功』归因于代码变更的结论前，先用运维回执（restart receipt 等）逐条比对故障动作与恢复动作的 git_head：同一 head ⇒ 运行的是同一份代码，『新代码补上支持』类归因被直接证伪，恢复必为回退/配置/运维因素；再到实际服务 head 的 .releases 快照（而非 live 工作树）定点验证字段/修复是否存在，并单独记录 live HEAD 是否恰为故障线。本集靠它把上一轮『gen210 新代码救场』的错误归因在提交前纠正为『手工退回上一代』，并新增了 live 树与配置仍不兼容的残留隐患。把『哪条代码线负责』从全部候选 head/全树枚举缩成一次机械比对 + 一次定点快照 grep。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e80a8cde-8a96-4b11-ad03-3f16341a32f5:1869:6e9515ae28f8fa776e87
evidence_refs: learning:learn:bae8f82196cd
created_at: 2026-10-09T15:06:28.961381+08:00
updated_at: 2026-10-09T15:06:28.961381+08:00
---
## Trigger
要对一次故障/恢复事件给出归因结论（RCA、演进建议、事后汇报），且存在记录每次动作 git_head/版本的操作回执；或对当前工作树 grep 某个『确在被使用』的配置字段返回为空时。

## Discriminator
故障与恢复两条回执的 git_head 相同 ⇒ 两次运行同一份代码，代码不可能是区分变量，任何『新代码修复/补上支持』的叙事被证伪，恢复只能归为回退/运维/瞬态因素；配合事实：字段在 live 树 grep 为空但曾被某代成功接受 ⇒ 注册代码在另一条 head，应去 .releases/<serving-head>/ 快照定点查证，并用 git rev-parse 确认 live 工作树 HEAD 是否本身就是故障线（本集 live HEAD=7fe0170d4 即故障代，而注册在 987f8642f 快照 resolver.py:95）。

## Short path
- 取故障时刻与恢复时刻的操作回执条目，读出各自 git_head/pid/时间戳
- 比对两个 head：相同 ⇒ 归因为回退/运维动作，删除一切『新代码救场』表述；不同 ⇒ 定位间隔提交，并在该 head 的快照中确认修复确实存在后才可归因代码
- 在 .releases/<实际服务 head>/src 定点 grep 字段/修复（不以 live 工作树 grep 空结果为准），同时 git rev-parse 记录 live HEAD 与故障线的关系，作为残留隐患写入结论
- 把修正后的归因 + 残留隐患（如 live 树与带字段配置并存会复现故障）写入建议后停止

## Stop conditions
- 故障/恢复回执的 head 已比对且归因已分类（同 head=回退/运维/瞬态；异 head=需快照验证修复后才能归因代码）
- 字段/修复已在实际服务 head 的快照中定位到具体文件行，或已证明该 head 确无注册

## Verification
- git rev-parse HEAD 的输出与故障回执的 git_head 一致，从而解释 live 树 grep 为空的原因（当前树就是缺注册的故障线）
- 在 .releases/<serving-head>/... 快照中找到字段注册的具体行（如 resolver.py:95），与 live 树缺失形成可复核的对照证据

## Counterexamples
- 恢复确实运行在包含修复提交的新 head 上（两 head 不同）⇒ 代码归因可能成立，但仍须在该 head 快照中验证修复后才可写入结论
- 无回执或回执不含 git_head/版本字段 ⇒ 本方法不可用，退回进程/日志记录
- 同 head 比对只能证伪『新代码救场』，不能区分回退、瞬态超时、端口/资源等其它原因；若故障本身是瞬态（head 与配置均未变），本方法对根因无结论力
- 问题只是『当前工作树里该字段是否已注册』以便立即改代码 ⇒ live grep 即权威答案，无需查快照
