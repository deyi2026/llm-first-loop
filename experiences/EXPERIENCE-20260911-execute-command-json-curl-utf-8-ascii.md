---
title: 经 execute_command 传 JSON 给 curl：全角标点易损坏成非法 UTF-8，载荷用纯 ASCII
scenario: "通过工具 shell 执行 curl POST JSON 且载荷含中文全角标点（：，。等），到达服务端可能变成非法 UTF-8（典型报错 UnicodeDecodeError: byte 0xbc，恰为全角字符 EF BC XX 的中间字节），服务器 400/连接层拒绝，易误判为服务端故障。"
root_cause: 命令经多层 shell/工具传输时全角字符字节序列可能被截断或重编码（EF 引导字节丢失后 0xbc 成为 invalid start byte）。
solution: "测试/冒烟载荷一律用纯 ASCII（英文 prompt + printf 构造 JSON 变量再 -d \"$BODY\"）；正式客户端用 HTTP 库原生 UTF-8 编码不受影响。排障时先看服务端 traceback 是否为 decode 错误而非崩溃。"
evidence: ""
tags: [curl, JSON, UTF-8, 全角字符, UnicodeDecodeError, 冒烟测试]
source: {}
status: active
created_at: "2026-09-11T08:44:56.468145+08:00"
updated_at: "2026-09-11T08:44:56.468145+08:00"
---