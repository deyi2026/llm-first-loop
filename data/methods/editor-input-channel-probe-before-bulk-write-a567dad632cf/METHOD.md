---
method_id: editor-input-channel-probe-before-bulk-write-a567dad632cf
name: editor-input-channel-probe-before-bulk-write
description: 向页面自带富文本编辑器批量写入带格式长文前，先用一段含结构标记的探针段落验证输入通道保真度：写前读 activeElement 确认焦点落地，写一段后读编辑器自身结构计数。出现字面量 ##/** 或整段退化成纯文本 span，即判定该通道是纯文本粘贴语义，改道「把目标格式 HTML 写进真实剪贴板 + 真实粘贴键注入」；点击无反应且 activeElement=BODY 则先 bringToFront 聚焦。禁止凭单次通道失败宣布『整条路走不通』，禁止不探针就整篇写入后返工，发布后以线上正文实测长度而非回执为真值。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:9f3f9ab8-30d9-4a2d-9f58-148054503778:1748:7b318dd211f467ec207d
evidence_refs: learning:learn:8e6e76b76da6
created_at: 2026-10-10T23:44:54.625915+08:00
updated_at: 2026-10-10T23:44:54.625915+08:00
---
## Trigger
需要向自带草稿自动保存/实时计数器的富文本编辑器（ProseMirror 类）批量写入带结构（标题/代码块/加粗/引用）的长文；或已观察到合成输入异常：点击无反应、文本上屏但结构丢失、编辑器计数与预期不符。

## Discriminator
两个写第一笔后即可读出、无需写完全文的事实：(1) 探针段写入后，编辑器自身结构显示 ##、** 以字面量留在纯文本 <span> 中（h2/pre 计数无增量）→ 当前通道（如 Input.insertText）是纯文本粘贴语义，保不了结构；(2) 点击无反应且 activeElement 是 BODY → 焦点/前台不在目标 tab，输入根本没进编辑器。

## Short path
- 绑定目标 tab 后先 bringToFront 并点击聚焦，读 activeElement 确认是编辑器节点再写第一笔
- 只写一段含结构标记的探针段落（如一行 ## 标题 + 一段加粗）
- 读编辑器自身计数/节点结构核对：标题计数+1 且无字面量 → 锁定该通道批量写入；出现字面量 span → 改道：把格式 HTML 写进真实剪贴板，用真实 Cmd/Ctrl+V 粘贴，再重跑单段探针
- 批量写入期间每次结构变更后读字数/图片数等编辑器自带计数作不变量，delta 不明即停
- 完成后用编辑器之外的权威界面（内容管理列表、线上正文实测长度/行数）确认，不把发布回执当真值

## Stop conditions
- 通道探针后编辑器结构计数增量正确（h2/pre/bold 各+预期值）且无字面量残留
- 全文写入后字数与结构计数与源稿同量级（本集实测 9884 字、h2×12、pre×2、blockquote×5）
- 编辑器之外界面确认线上正文长度/行数与源稿一致

## Verification
- 每次切换输入通道后重跑单段探针，不得凭推断跳过
- 发布后读线上正文实测长度/行数，与源稿对比，回执仅作参考
- 每次写入前确认 activeElement 为编辑器节点
- 结构变更前后记录编辑器自带计数，未解释 delta 当步处理

## Counterexamples
- 纯文本内容（无标题/代码/加粗结构）：insertText 直接可用，剪贴板探针是纯开销，还引入剪贴板被其他进程占用的风险
- 普通静态表单（登录、搜索框）：无编辑器模型与草稿重载，native setter+change 即可，探针纪律不适用
- 平台提供一等内容导入 API/CLI 或编辑器自带导入入口：直接使用，跳过按键级通道工程
- 编辑器既无结构计数器也无法读节点结构：探针的验证面不存在，应改用 DOM diff/截图对比而非本方法
- 单次短字段输入：探针成本高于收益
