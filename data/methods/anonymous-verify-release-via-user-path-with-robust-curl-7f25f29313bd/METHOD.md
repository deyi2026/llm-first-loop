---
method_id: anonymous-verify-release-via-user-path-with-robust-curl-7f25f29313bd
name: anonymous-verify-release-via-user-path-with-robust-curl
description: 对外发布（release 转正等）后需以匿名/未认证视角核验可达性与字节一致性时，第一跳走用户真实路径（releases/latest 重定向 + 资产下载 URL），不要先打 REST API：API 属另一客户端类，其 per-IP 配额 403 与『是否公开可见』这一问题正交；JSON 解析 KeyError 时先看原始响应体/状态码再归因。匿名下载大工件直接用稳健调用 curl -sSL --http1.1 --retry 3 --retry-all-errors：退出码 16（HTTP/2 framing）/35（SSL_ERROR_SYSCALL）是传输层瞬时错误而非 404 终态，幂等 GET + 已知期望 sha256 使激进重试安全；一次升级全部 flags，省去单 flag 试错链。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7c026852-7867-4a41-9ab0-1340271874dc:1037:ff42255621fde3597ab9
evidence_refs: learning:learn:855c115f5059
created_at: 2026-10-22T15:26:05.516043+08:00
updated_at: 2026-10-22T15:26:05.516043+08:00
---
## Trigger
已执行对外发布动作（release 转正、公开上传、部署）后，需要从未认证用户视角验证：入口/latest 指向正确版本、资产可匿名下载且字节与发布时核验过的摘要一致

## Discriminator
回执本身已给出失败层级分类依据：HTTP 403 + rate-limit 报文体 = API 客户端类配额问题，不回答可见性问题；curl 退出码 16/35 = 传输层瞬时错误，非 4xx 终态；且下载是幂等 GET、期望 sha256 已在发布前核验过——换协议与重试零风险且可用独立重算验证

## Short path
- 未知量=latest 是否指向目标版本：匿名取 releases/latest 的最终重定向 URL（curl -sL -o /dev/null -w %{url_effective}），不经 API、不消耗配额
- 未知量=资产字节一致：对 SHA256SUMS 与目标工件一次性使用稳健调用 curl -sSL --http1.1 --retry 3 --retry-all-errors --retry-delay 2 下载并独立重算摘要，与发布前已核验值比对
- 若某 JSON 解析报 KeyError：先 curl -D 看原始状态码与响应体，区分配额/形状/缺失三类，再决定换路径或带认证，不改解析代码
- 重定向指向目标 tag 且匿名下载摘要一致即停止，不追加确认性调用

## Stop conditions
- 匿名视角下 releases/latest 最终 URL 指向目标 tag，且至少关键工件 sha256 与发布清单逐字节一致
- 出现 404/401 等终态：停止重试与换 flag，判定资产缺失或未公开，转入发布侧排查

## Verification
- 全程无 token 环境执行，确认核验的确实是匿名可达性
- 下载完成后本地独立重算 sha256，不信任传输过程回显或清单自证
- 与发布前 Draft 阶段已核验的 SHA256SUMS 值对照，而非仅与本次下载的清单对照

## Counterexamples
- 核验目标本身就是机器客户端行为（第三方 CI 用 API 拉取）→ 必须走 API 并处理配额/认证，web 重定向答非所问
- curl 退出码 6（DNS 解析失败）或 4xx 终态 → 重试与降级 HTTP/1.1 无效，应判网络中断或路径错误
- 非幂等请求（POST 发布、下单、群发）→ 严禁 --retry-all-errors，会重复不可逆副作用
- 小型 JSON 端点且网络稳定 → 默认 flags 一次即成，预先加满 flags 属过度工程
