---
title: LFL 沙盒内桌面写动作：AXPress 与 AX set-value 可用，CGEvent 键入被 macOS SCIM 输入法污染
scenario: 在 LFL 沙盒进程（sandbox-exec，仅允许写工作区与缓存目录）内验证 macOS 桌面写动作通道是否真的投递：AXPress 动作、AX 值写入（键入）、CGEvent 键入事件三种路径，在 TextEdit 临时窗口上做。
root_cause: AX 动作/值写入走 Mach IPC 的 AX 通道，与 AppleEvent 不同，不受沙盒限制；CGEvent 走 HID event tap，输入法在按键与应用之间插入组词与提交行为，故输出被污染。
solution: "1) AXPress 真投递可直接用 AXUIElementPerformAction(el, \"AXPress\")，对原生 AXCloseButton 按下后窗口数 1→0，可作 A 级证据；2) AX 键入用 AXUIElementSetAttributeValue(el, kAXValueAttribute, str) 写 AXTextArea/AXTextField 后回读，完全一致，是最可靠的键入通道；3) CGEventPost(kCGHIDEventTap) 的键事件能送达目标应用，但本机输入源为 com.apple.inputmethod.SCIM（拼音 ABC）时逐字母会被输入法组词并用空格提交（\"asd\" 变成 \"a s d\"），带 shift 的大写不受影响，纯 unicode 事件（keycode=0）无输出——因此 CGEvent 兜底路径必须先切 ASCII 输入源或逐字符回读校验。"
evidence: "evidence://v1/7a9f00ca4a223ce45fa107236113dbdd2e613733b62cc0d3229422a69a2929d7（AXPress err=0 窗口 1→0；AX set-value 回读一致）、evidence://v1/96e5c00a18efe10ba899c3b40a2600f729f4bb3b4dd2be92f0a5ecd95c947f（T1 \"a s d\"、T2 \"ASD\"、T3 无输出）、evidence://v1/5ee7b3（AppleSelectedInputSources = SCIM）"
tags: [macos, ax, cgevent, ime, desktop_operate, sandbox]
source: {}
status: archived
record_kind: experience
verification_state: verified
created_at: "2026-10-31T15:20:20.828474+08:00"
updated_at: "2026-10-31T15:20:37.908055+08:00"
---