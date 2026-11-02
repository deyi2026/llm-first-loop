---
title: CGWindowList 对已销毁窗口有残留条目：验证「动作生效」要双口径（CG + AX），否则假阴性
scenario: 验证「桌面动作是否真的生效」时，用 CGWindowList 判断目标窗口是否消失，会在动作已生效的情况下误报「窗口还在」（CG 列表对已销毁窗口有残留条目）；此时若继续走清理分支，会给出误导性提示，甚至把已完成的投递当成失败重做。
root_cause: ""
solution: 窗口是否消失要**双口径判定**：CGWindowList 缺失 **或** AX 侧解析不到该窗口（AXUIElementCreateApplication → AXWindows 里没有目标标题）→ 判为已消失；只信 CG 列表会假阴性。AX 投递（AXPress）是异步生效的，校验前先留 settle 窗（数秒）再判定。
evidence: "live 实测：apply ok=true/applied=true/post_sha256≠pre_sha256，事后 Preview 窗口列表为空（窗口确实关闭），但脚本当时报「已消失: False」并给出「请手动关闭窗口」的误导提示；加 AX 侧兜底后判定稳定为 True（用例 10/12）。"
tags: [macos, AX, CGWindowList, live-验证, 假阴性, desktop]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T20:25:23.857751+08:00"
updated_at: "2026-10-31T20:25:23.857751+08:00"
---