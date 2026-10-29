---
title: fcitx5 变更后 dbus 读回通过≠实际生效：图形会话需完整重启，验收以用户打字为准
scenario: deepin 输入法配置变更后，dbus 层验证通过但用户实测失败，需要判定是配置错误还是生效延迟
root_cause: ""
solution: 1) 写入配置+重启进程后，dbus CurrentIM 切换读回仅证明 fcitx5 守护进程内部状态正确；2) 各应用接入输入法的路径要图形会话重新加载配置，被 watchdog 接管过实例后尤其如此；3) 引导用户注销或完整重启后再实测打字，以用户实测为最终验收；4) 本地沙箱无法跑 fcitx5 工具，远程诊断走 ssh 192.168.3.x
evidence: "会话 c7e4e166（2026-10-29）：10:13-10:16 dbus 层切换测试读回 com.sogou.ime.ng.fcitx5.deepin 成功（execute_command 回执）；12:47 用户报告重启后仍不能输入中文；12:48 用户实测反馈\"可以输入中文了\"。验收=用户实测。"
tags: [fcitx5, deepin, input-method, ssh, 生效延迟]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T12:49:00.518538+08:00"
updated_at: "2026-10-29T12:49:00.518538+08:00"
---

用户 deepin 机器 (ssh -o BatchMode=yes 192.168.3.x，本机 execute_command 是 macOS 沙箱，fcitx5 工具均不可用) 上精简 fcitx5 输入法组为 keyboard-us + 搜狗拼音、DefaultIM 设搜狗。配置写入、进程重启、dbus CurrentIM 切换读回全部通过，用户仍报告打不出中文。解决：完整重启机器后用户确认可输入中文。教训：dbus 层测试只是必要非充分条件，图形会话级输入法变更（尤其 fcitx5-helper watchdog 接管过实例后）以完整会话重启为生效判据；最终验收必须是用户实际打字，不能以 dbus 读回代替。