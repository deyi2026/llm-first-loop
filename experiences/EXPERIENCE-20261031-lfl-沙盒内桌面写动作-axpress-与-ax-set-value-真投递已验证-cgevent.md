---
title: LFL 沙盒内桌面写动作：AXPress 与 AX set-value 真投递已验证，CGEvent 键入被 macOS SCIM 输入法污染
scenario: 在 LFL 沙盒进程（sandbox-exec，仅允许写工作区与缓存目录）内验证 macOS 桌面写动作通道是否真的投递：AXPress 动作、AX 值写入（键入）、CGEvent 键入事件三条路径，在 TextEdit 临时窗口上做。
root_cause: ""
solution: "1) AXPress 真投递用 AXUIElementPerformAction(el, \"AXPress\")：对原生 AXCloseButton 按下后窗口数 1→0，可作 A 级证据；2) AX 键入用 AXUIElementSetAttributeValue(el, kAXValueAttribute, str) 写 AXTextArea/AXTextField 后回读，完全一致，是最可靠的键入通道；3) CGEventPost(kCGHIDEventTap) 的键事件能送达目标应用，但本机输入源为 com.apple.inputmethod.SCIM（拼音 ABC）时逐字母会被输入法组词并用空格提交（\"asd\" 变成 \"a s d\"），带 shift 的大写不受影响，纯 unicode 事件（keycode=0）无输出——CGEvent 兜底路径必须先切 ASCII 输入源或逐字符回读校验。另注：取 AXChildren 后不可立即 CFRelease 容器，否则子 AXUIElementRef 失效会段错误。"
evidence: "AXPress+AX set-value：evidence://v1/7a9f00ca4c223ce45fa107236113dbdd2e613733b62cc0d3229422a69a2929d7；CGEvent 三组对照：evidence://v1/96e45c00a18efe10ba899c3b40a2600f729f4bb3b4dd2be92f0a5ec6d95c947d；输入源 SCIM：evidence://v1/6f30b2a3ef1bc084d267f40a3638a9a9a54fd8e6ec80b07bebe33e49a4a168ae"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T15:20:43.387835+08:00"
updated_at: "2026-10-31T15:20:43.387835+08:00"
---