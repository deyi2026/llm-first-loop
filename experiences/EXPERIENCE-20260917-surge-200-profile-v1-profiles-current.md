---
title: Surge 热重载 200 ≠ 生效：必须改激活 profile 源文件并用 /v1/profiles/current 核验
scenario: macOS Surge 修改配置后 API 热重载返回 200 但运行配置未变化；本例为机场订阅 managed profile 的死 DoH 修复
root_cause: ""
solution: 先用 GET /v1/profiles/current 确认激活 profile 名（返回 JSON 的 name 字段），编辑 Profiles/<name>.conf 源文件而非 .managed/ 缓存；改完 POST /v1/profiles/reload，用 /v1/profiles/current + 日志时间戳双重复核生效
evidence: "evidence://v1/dc5538b5b92cd236e258c32b330c3d561b92651bf9cf737fe6a47d682206cca4 (死DoH REFUSED日志); /v1/profiles/current 返回 name=Nexitally_Surge 且修复后 encrypted-dns-server 计数=0; 规则模式 google HTTP 204×3、baidu 200、重载后 SGDNSClient 报错 0"
tags: [surge, dns, doh, hot-reload, macos, proxy]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-17T01:38:47.587420+08:00"
updated_at: "2026-09-17T01:38:47.587420+08:00"
---

现象：修改 $HOME/Library/Application Support/Surge/Profiles/.managed/<hash>.conf 后调 POST /v1/profiles/reload 返回 HTTP 200，但运行配置未变（Surge 日志仍按旧配置行为报错）。
机制：Surge 5 的 .managed/ 目录是 include 展开的编译缓存；激活 profile 的配置源是 Profiles/<name>.conf（#!include 订阅 URL 的文件）。改缓存不改变源文件，reload 只是重新读取源文件。
正确做法：
1. GET /v1/profiles/current（header: X-Key）返回字段 name 即激活 profile 名，与 Profiles/ 列表对照找源文件；
2. 备份后直接编辑 Profiles/<name>.conf，再 POST /v1/profiles/reload；
3. 验证三件套：再次 GET /v1/profiles/current 确认改动生效；log show --last Nm --predicate 'process == "Surge"' | grep SGSNSClient 看 DNS 报错时间戳是否停在重载前；curl -x http://127.0.0.1:6152 端到端实测。
本例：Nexitally_Surge.conf 的 encrypted-dns-server 三个 DoH 全部 REFUSED，规则模式下境外域名解析失败；注释该行+重载后 Google HTTP 204、百度无回归。注意 grep -c 返回 0 匹配时 exit 1，set -e 脚本会把成功误判为失败。