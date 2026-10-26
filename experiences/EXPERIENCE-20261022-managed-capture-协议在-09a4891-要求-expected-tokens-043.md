---
title: managed capture 协议在 09a4891 要求 expected_tokens（04329aa 老 driver 直接 400）
scenario: 字节预算对照单元复用 20260907 managed_ram_ab driver 原语，对 09a4891 重建二进制首次 capture 即 HTTP 400
root_cause: ""
solution: 拷贝库段+capture 载荷补 expected_tokens；跨版本复用 managed 协议 driver 前先查该谱系协议变更 commit
evidence: "evidence://v1/7dfd627a5b828e5b61b5903cd4a12a0d93c835ff1281a796ed9f101d0c4cde79"
tags: [statebraid, managed-m1, capture-protocol, expected_tokens, driver-compat]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-22T19:07:59.119952+08:00"
updated_at: "2026-10-22T19:07:59.119952+08:00"
---

llama.cpp-statebraid-managed-m1 谱系（04329aa → 09a4891）中 commit 102a238「bind managed capture to exact tokens」把 POST /statebraid/cache action=capture 的协议改为必填 expected_tokens（token 列表）。20260907 时期的老 driver（managed_ram_ab.py 等）capture 载荷不带该字段，对 09a4891 构建一律 400 且服务端日志无明确错误行（错误体只在 HTTP 响应里）。适配方式（保真）：拷贝老 driver 的库部分（1-379 行）为新文件，capture 载荷补 expected_tokens: list(prompt)，diff 记录在 RECORD；原件不动。