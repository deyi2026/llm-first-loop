---
method_id: role-projected-snapshot-for-interaction-targets-7b9da98b63e3
name: role-projected-snapshot-for-interaction-targets
description: 在巨大或被截断的 DOM 语义快照中定位交互元素时，先按 role/kind 过滤投影（input/button/textarea），而不是对全量 dump 做线性分页读。未知量应定义为'目标角色的当前 grounded id'，而非'整页内容'。每次 mutation 或导航（document_generation_changed）后，用新的过滤快照重新解析 id 再引用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:1061:04cddd24ab158d01b780
evidence_refs: learning:learn:8dba3e6c591e
created_at: 2026-09-18T19:17:00.108947+00:00
updated_at: 2026-09-18T19:17:00.108947+00:00
---
## Trigger
需要在大型/被截断的语义快照（DOM/ax 对象 dump）中定位特定交互元素（输入框、按钮），而全量分页读会枚举大量 StaticText/generic 噪声时

## Discriminator
首个快照（即使截断）已显示两个当时可见的事实：每个对象都带 role/kind 元数据；dump 主体是 StaticText/generic 噪声，而任务目标只是极少数角色（密码 textbox + 登录 button）。这条事实在开始分页前就足以把'读整页'缩成'只取目标角色'，无需任何后续才知道的答案

## Short path
- 把未知量写成角色级目标：'目标 input/button 的当前 grounded id 是什么'
- 对快照工具发起仅含交互角色的定向/过滤投影，一次取得候选 id 集合
- 若工具不支持过滤，按 dump 中的角色标记跳读（定位 role=button/textbox 条目），不做 0→N 的逐页线性读
- 对每个 id 执行动作并核对回执 target_id 与 verb/status；导航或文档代次变化后先重新过滤快照取新 id
- 过滤投影为空或目标角色缺失时，才退回全量快照/分页检索

## Stop conditions
- 每个交互目标都从同一份最新过滤快照取得 grounded id，且动作回执 target_id 与之匹配、status=ok
- 过滤投影确认无目标角色，已按需退回更宽观察方式

## Verification
- 动作回执的 target_id 与过滤快照中的元素 id 一致，verb 正确、status=ok
- click 导致 document_generation_changed/scope_changed 后，不引用旧 id，先重新过滤快照
- 最终交互结果由页面状态或服务端记录确认（如登录成功进入新 scope）

## Counterexamples
- 目标事实在静态文本内容里（页面说明、提示文案、正文），input/button 过滤会把信息过滤掉，应读正文投影或分页全文
- 页面很小、一次快照已 complete=true，过滤反而是多余一步
- 证据检索（如 search_evidence）能直接命中目标标签时，一次检索更省；只有检索探测失败后才退到过滤快照分页读
