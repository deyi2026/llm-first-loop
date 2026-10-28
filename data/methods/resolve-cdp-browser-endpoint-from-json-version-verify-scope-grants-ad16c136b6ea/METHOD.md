---
method_id: resolve-cdp-browser-endpoint-from-json-version-verify-scope-grants-ad16c136b6ea
name: resolve-cdp-browser-endpoint-from-json-version-verify-scope-grants
description: 向 CDP/DevTools 类控制协议发 browser 级命令（如 Browser.grantPermissions）时，browser ws 地址是带 UUID 的动态值：先一次 curl /json/version 取真实 webSocketDebuggerUrl，不要猜路径，也不要在 non-101 后改走页面级会话发 Browser.* 命令——页面级回执可能是 success 形状但实际不生效，会把故障推迟到端到端探针中途以「权限被拒绝」爆发，浪费一整轮探针。授权类命令必须用权限状态查询或最小真实操作确认生效，{} 回执本身不算验证。
aliases: CDP browser websocket 地址去哪拿, devtools 授权回执成功但页面仍权限被拒, 9229 non-101 浏览器级握手失败, grantPermissions 没生效 授权回执成功但页面仍拒绝, 猜浏览器调试端点失败先查 json version
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:80f5e2cd-19c2-42bb-8bca-1c0a01cc2a48:5065:85af0491e304c8ece4f2
evidence_refs: learning:learn:f59bda6ec90f
created_at: 2026-10-28T03:22:26.402507+08:00
updated_at: 2026-10-28T03:22:26.402507+08:00
---
## Trigger
需要 browser 级（会话全局）控制命令（授权、目标管理、协议级设置），但手中只有 target 列表回执、browser ws 地址未出现；或对猜测的 browser 端点握手收到 non-101，正想改走页面级会话绕过

## Discriminator
target 列表里每条 webSocketDebuggerUrl 都带 per-target UUID——browser 端点同构、猜不出；权威来源是 /json/version 的 webSocketDebuggerUrl 字段，一次 curl 即得。non-101 = 地址错而非服务不可用；错误 scope 会话上的 success 回执不证明命令生效

## Short path
- 识别命令需要 browser scope → 唯一未知量：browser ws 端点是什么 → curl /json/version 解析 webSocketDebuggerUrl
- 用真实端点（UUID 匹配）建 ws，发送 Browser.* 命令，等待显式 result 或 error
- 用权限状态查询或在受影响页面触发最小真实操作（如 getUserMedia）验证生效，而不是只信 {"result":{}} 回执
- 回执 success + 状态/操作双确认后才进入昂贵的端到端探针（按住→发声→释放）

## Stop conditions
- browser 命令返回显式 error（domain/method 不支持）→ 是协议能力问题，转向替代机制，不再排查地址
- 回执 success 且权限状态查询或最小真实操作确认生效 → 端点与授权排查结束，进入功能探针
- /json/version 中端点与当前连接一致且页面级操作正常 → 无需更多通道验证

## Verification
- 在受影响页面查 navigator.permissions 状态或直接触发 getUserMedia，确认权限真实生效而非仅回执为空对象
- 所用 ws 端点字符串与 /json/version 当前返回逐字一致（UUID 匹配）
- 探针失败时先比对页面报错与授权状态，区分『从未授上』与『授上后被刷新重置』

## Counterexamples
- 纯页面级操作（点击、Runtime.evaluate、读 DOM、注入事件）：page ws 已够，不需要 browser 端点，此时先查 /json/version 是多余开销
- 协议处于 flatten/proxy 模式，Browser.* 经页面会话真实转发且状态查询已确认 granted：不必重走 browser 端点
- non-101 由端口不可达/服务未启动引起（页面级 ws 同样连不上）：问题是服务不在，地址发现无济于事
- 页面报权限被拒但状态查询显示 granted：可能是刷新后 permission 作用域/origin 变化，应查作用域而非端点
