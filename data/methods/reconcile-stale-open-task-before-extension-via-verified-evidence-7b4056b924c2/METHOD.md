---
method_id: reconcile-stale-open-task-before-extension-via-verified-evidence-7b4056b924c2
name: reconcile-stale-open-task-before-extension-via-verified-evidence
description: 在已有 goal/task 图上新增下一阶段 task 前，先读权威 tracker（get_goal/task_frontier）：若上轮自述已完成却仍有 open/in_progress 节点，先收口该 stale task 再扩展。收口不靠对 evidence 库换措辞猜测搜索，而是按 task 标题命名的交付物直接定位并 read_file 取内容事实；当状态闸做证据真实性校验时，read_file 类证据常为 verified_current 可一次过闸，freshness=unknown 的命令回执会被拒，应改引已验证证据而非重复提交同一引用。新 task 的验收口径逐条引自权威文档原文小节。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:367:0b6ded654e7df735899b
evidence_refs: learning:learn:fe38f7fb7c86
created_at: 2026-10-15T00:48:00.421277+08:00
updated_at: 2026-10-15T00:48:00.421277+08:00
---
## Trigger
活动 goal/task 图存在，用户要求新增下一阶段 task；或 get_goal/task_frontier 显示的状态与上轮自述结论不一致（声称 done 的 task 仍 in_progress），需要对已宣告完成的 task 做状态收口。

## Discriminator
①权威 tracker 的 open 状态与上轮自述 done 相矛盾，且该 task 标题本身已命名交付物（如 recount/thin_links/exit_layers 对应『复算基线/稀薄链路/退出分层』），outputs 交付物可按名一次定位；②收口工具回执『证据真实性校验失败 unresolved_or_not_authorized』时，evidence 库状态显示 read_file 证据 freshness=verified_current 而命令回执 freshness=unknown——前者才是可过闸引用。

## Short path
- get_goal + task_frontier 取权威状态；发现 stale open task 即暂停新立项，先核实收口
- 按 task 标题命名的交付物名做一次 search_files/ls 定位 outputs 产物，不对 evidence 库做措辞猜测搜索
- read_file 读关键交付物取内容事实并生成 verified 证据；shasum/git status 佐证产物与零副作用声明
- 收口 stale task 时只引用 verified_current 的读证据；若闸拒绝，先查证据库中各引用的校验状态再换引用，不重复提交同一引用
- 重读 frontier 确认该 task done 且 evidence_verified 后，读权威文档相应小节（如阶段表与 schema 示例），以原文验收口径创建新 task

## Stop conditions
- tracker 与上轮自述一致且无 stale open 节点：跳过收口，直接立项
- 交付物缺失或与上轮声明不符：不强行收口，按真实遗留工作重新处理
- 收口后 frontier 确认 done+evidence_verified：停止核验，进入新 task 立项

## Verification
- 收口完成后重读 task_frontier：目标 task 状态=done 且 evidence_verified=verified
- 新 task 的 acceptance 每条可回溯到权威文档的具体小节/行，而非自编口径
- git status 复核只读约束：源码、账本、配置目录零改动

## Counterexamples
- frontier 与自述一致且无 stale 节点时：核对-收口是纯开销，应直接立项，不预防性重查
- 交付物是外部副作用（部署、DB、远端状态）而非本地文件：按文件名定位法失效，须查该副作用自身的权威记录
- 待证事实只能由命令回执证明（如 git status 零改动）：read_file 证据不覆盖该断言，需与命令证据配对或接受额外一步，不能机械只引读证据
- 无证据真实性校验闸的环境：verified_current 与 unknown 的区分无意义，收口引用规则不可套用
