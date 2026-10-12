---
method_id: connection-refused-resolve-actual-port-via-pid-socket-table-a77a0862065a
name: connection-refused-resolve-actual-port-via-pid-socket-table
description: 当用户报告某本机 URL/端点“出错”，首次探测返回传输层拒绝（curl exit 7 / ECONNREFUSED，0ms 失败、无 HTTP 响应）时，故障类别立即定为“该地址无监听者”（地址不匹配或服务未起），不是服务端故障。若一条 status/ps 调用即可得知声称存活的服务 PID，则该进程的内核 socket 表（lsof -p PID / ss -p）是“实际监听哪个端口”的唯一权威单跳答案：直接查它，而不是先做仓库配置文本搜索或宽端口扫描。配置文件描述意图、可能过期且易被 evals/测试数据污染；socket 表才是运行时事实。本集用此法把 8 次调用、含一次被污染的全仓 grep 压缩到 4 步可信路径（curl→status(pid)→lsof→curl 新端口）。
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:5fcf6937-6354-42af-bfe0-63e56f15696a:0:35eb530b0531c7d9f111
evidence_refs: learning:learn:a66201e98799
created_at: 2026-10-05T20:11:04.682298+08:00
updated_at: 2026-10-05T20:11:04.682298+08:00
---
## Trigger
用户报告某本机 URL/端口“出错”；首次 curl 返回 connection refused / couldn't connect（非 HTTP 错误码）；且 status/ps 可给出一个声称存活的服务进程 PID。

## Discriminator
curl 报 ECONNREFUSED（0ms、无任何 HTTP 响应）= 该端口上无监听者，问题类别是“地址不匹配”而非“服务故障”；同一时点已知存活 PID → “它实际监听哪个端口”由该 PID 的 socket 表一步可答，无需任何文本发现。

## Short path
- curl 用户给的 URL，先读错误类别：refused(0ms)=无监听→转地址核实；HTTP 4xx/5xx=端口有监听→查应用层，不走本方法
- 从 status/ps 取该服务存活 PID（解决未知量：哪个进程是服务本体）
- 对该 PID 直接 lsof -p（或 ss -p），读 LISTEN 行得实际端口（解决未知量：真实端口）
- curl 实际端口（/ 或 /health）验证 HTTP 层可服务，即得到可用地址，回答用户并停止

## Stop conditions
- 已从目标进程 socket 表取得 LISTEN 端口，且 curl 该端口返回 HTTP 层响应（如 307/200/health 200）——用户所需事实已被权威来源验证
- socket 表显示该 PID 无任何 LISTEN → 问题变为“服务未启动/启动失败”，转查启动配置与日志，不再做端口发现

## Verification
- curl 实际端口得到 HTTP 响应，且与 lsof 的 LISTEN 行一致（端口、绑定地址均吻合）
- 可选：交叉核对一份声明性配置（如 .env 的 PORT 项）；不一致时以 socket 表为运行时事实并向用户说明差异

## Counterexamples
- curl 返回 HTTP 5xx/4xx：端口有监听，问题是应用层错误，应查服务日志而非换端口找监听者
- status/ps 未给出 PID、服务进程未知：pid-单跳法前提不成立，此时 lsof -iTCP -sTCP:LISTEN 全监听扫描才是直接观测
- 服务跑在容器/远端主机：本机 PID 的 socket 表看不到它，需到正确 namespace/主机上观测
- 用户问的是“配置应该是什么”而非“实际在听哪”：这是声明性问题，应读配置与 git 历史，而非 socket 表
- PID 存活但无 LISTEN：说明 worker 挂了或未绑定，不是端口写错，转启动面排查
