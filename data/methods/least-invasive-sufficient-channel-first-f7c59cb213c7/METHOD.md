---
method_id: least-invasive-sufficient-channel-first-f7c59cb213c7
name: least-invasive-sufficient-channel-first
description: 在用户已登录的桌面 GUI（如浏览器）里做只读获取时，先按任务最小能力需求（打开URL/看内容/滚动）选通道，而不是先追求最强控制协议。本集为读一个已登录 Chrome 页面，先花两轮重启尝试打通 CDP 调试口（默认 profile 被 Chrome 136+ 已知静默忽略，symlink 伪装也失败，还两次退出了用户的 Chrome），之后才试 AppleScript+截屏+键盘滚动，一次即通且零侵入。判别事实在第一跳已存在：任务只读 + 版本≥136 + 默认profile ⇒ 协议通道必然要 hack；而读屏不需要 CDP。正确顺序是先批量探测零侵入通道（open/activate+取URL+截屏权限），够用即停；仅在需要结构化 DOM/JS、无 GUI 或无截屏权限时才升级侵入式通道。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a962d90b-199e-4a0c-af2f-3ce28b719bfb:99:22cb389f16f2b7bb7668
evidence_refs: learning:learn:72beb28013dc
created_at: 2026-09-23T01:05:46.535983+00:00
updated_at: 2026-09-23T01:05:46.535983+00:00
---
## Trigger
需要在用户本机已登录的 GUI 应用（浏览器等）中读取/观察内容；同时存在多条控制通道：需重启改启动参数的协议级控制（CDP/调试口）与零侵入系统级自动化（open、AppleScript、截屏、键盘事件），且任务本质是只读观察

## Discriminator
两个当时已知事实：(1) 任务只需视觉读取已登录页面内容，不需要 DOM/JS 级控制；(2) 首次探测已显示 Chrome 153 运行在默认 profile 且 9222 未监听，而 Chrome 136+ 对默认 profile 会静默忽略 --remote-debugging-port——即协议通道注定要侵入式 hack（换 profile 丢登录态，或 symlink 等不确定手段），而任务根本不需要该通道。待解的未知量应是"哪条最便宜通道能拿到内容"，而非"如何解锁 CDP"

## Short path
- 列出任务最小能力需求（打开链接、看内容、滚动到底），确认无需 JS/DOM 级控制
- 用已知版本/profile 限制预判通道成本：≥136+默认profile ⇒ 调试口需侵入 hack，直接降优先级，不消耗重启轮次
- 一条批量命令探测零侵入通道：open 目标URL（或 AppleScript activate + get URL of active tab）+ screencapture 权限试探
- 对最前窗口截屏做视觉读取；用 System Events 键盘滚动后再次截屏，直到出现页尾标志（输入框/免责声明/最后一条消息）
- 验证多屏覆盖完整内容、相邻屏衔接一致，清理临时截图；全程不重启应用、不加调试参数、不动登录态

## Stop conditions
- 视觉读取已覆盖目标内容全部（出现页尾标志且首尾消息均可见）即停止，不再尝试打通更强控制通道
- 零侵入通道被证伪（无截屏权限、内容超出视觉可读精度、需结构化数据/交互触发）时，才升级到侵入式通道并明示代价（重启、丢登录态、临时 profile 清理）

## Verification
- 截屏中出现页面末尾标志（输入框/免责声明/最后一条消息）且与上一屏内容衔接一致，无跳读段落
- 用户会话未被改动：应用无残留调试参数或临时 profile/symlink，登录态完好，临时文件已删除

## Counterexamples
- 任务需要精确 DOM 文本、执行 JS 或超长文本逐字提取时，截屏+视觉读取有损，升级 CDP/脚本通道才是正解
- Chrome <136、调试口已在监听，或无 GUI/无截屏权限的环境：零侵入通道不可用或更慢，协议通道反而是最短路径
- 页面内容需交互后才加载（点击展开、悬停显示）：仅截屏+滚动不足，需键鼠合成或脚本控制的混合方案
