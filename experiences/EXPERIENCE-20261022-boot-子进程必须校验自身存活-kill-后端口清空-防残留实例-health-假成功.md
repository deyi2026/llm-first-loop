---
title: boot 子进程必须校验自身存活+kill 后端口清空，防残留实例 health 假成功
scenario: 字节预算 A/B driver 首轮：校准实例因 admit 400 异常退出时未被 kill，第二次 boot bind 失败但 health 探测命中残留实例而「成功」，导致后续 cell 全部跑在错误预算的服务器上
root_cause: ""
solution: boot 校验自 proc 存活（poll 检查 ×2）+ kill_server 后验证端口 LISTEN 清空；两者任一失败确定性报错
evidence: "evidence://v1/7dfd627a5b828e5b61b5903cd4a12a0d93c835ff1281a796ed9f101d0c4cde79"
tags: [subprocess, port-collision, llama-server, health-check, isolation]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-22T19:07:38.792526+08:00"
updated_at: "2026-10-22T19:07:38.792526+08:00"
---

自管子进程（如隔离 llama-server）的 boot 函数只做「health OK 即返回」不够：上一实例异常路径（如 driver 在 kill 前抛异常退出）残留时，新进程 bind 失败死掉，而 health 探测命中的是残留旧实例——后续整个 cell 跑在错误配置的服务器上且难以察觉（本轮 managed-2048 cell 因此跑在 512MiB 服务器上）。修复：① boot 循环里先查自 proc.poll()！=None 立即报错（port collision）；② health OK 后再查一次自 proc 存活才返回；③ kill_server 结尾轮询 lsof 端口 LISTEN 清空（≤20s），未清空报错。补丁后同类残留被确定性拦截。