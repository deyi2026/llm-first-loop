---
method_id: precheck-credential-origin-binding-before-browser-e2e-50b377436e63
name: precheck-credential-origin-binding-before-browser-e2e
description: 做浏览器端到端验收（语音/WebSocket 等交互链路）时，先别在顺手 origin（如本地面板）上驱动完整 UI happy path。先用一对静态事实判定可行性：安全设计声明的握手凭证形式（如必须浏览器会话 cookie、Bearer 被拒）+ 部署配置的绑定域（cookie domain/origin 白名单）。若绑定域与探测 origin 不匹配，该链路在配置层即被排除，且失败是静默的：客户端全通（建会话 201、扬声器播报）也无信息量。正确下一步是切换到能满足绑定的真实入口（如公网主域）执行验收；命中登录墙等凭证硬阻塞时停止叠加绕过，向用户要最小动作。服务级样本不得混入浏览器链路口径。一次静态比对即可把『任何 origin 都可能通』缩为『只有绑定域能通』，省掉整段注定无效的 UI 驱动与交互层排查。
aliases: 本地点得通但服务端收不到先查cookie域, 语音验收前核对握手凭证和origin, UI正常链路静默失败, 127.0.0.1拿不到公网域cookie, 浏览器链路验收换到真实域名入口跑
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:80f5e2cd-19c2-42bb-8bca-1c0a01cc2a48:3871:2d27eda68c64ca46b939
evidence_refs: learning:learn:bcedd98eab76
created_at: 2026-10-26T08:05:04.381785+08:00
updated_at: 2026-10-26T08:05:04.381785+08:00
---
## Trigger
需要以真实浏览器链路（点击/麦克风/WebSocket 通道）做验收、探针或性能采样，且该链路握手依赖会话 cookie/origin 绑定类凭证；准备驱动 UI 前未核对『凭证绑定 vs 探测 origin』是否兼容

## Discriminator
两份静态可读事实的合取：①设计/安全文档（本轮已读）已声明握手凭证形式（WS 握手必须浏览器会话 cookie，Bearer 会被拒）；②一次部署配置读取即可得到的绑定域（cookie domain 指向公网主域而非本地 host）。比对即把『所有 origin 都可能通』缩为『只有绑定域能通』，无需任何 UI 驱动即可判定本地链路被结构性、静默地排除

## Short path
- 从任务书确认验收口径=浏览器链路端到端、非 mock（未知量：验收必须走哪条链路）
- 驱动任何 UI 前先解决一个未知量：探测 origin 能否满足握手鉴权？一次性读安全设计的握手凭证要求 + 部署配置的 cookie/origin 绑定域
- 若绑定域与探测 origin 不匹配 ⇒ 记录『该 origin 链路被配置结构性排除且静默（UI 可用≠链路可用）』为发现，不用 happy path 取证
- 切换到满足绑定的真实入口（绑定域对应的公网地址）执行探针与采样
- 命中登录墙且凭证不可自造 ⇒ 停止绕过，向用户请求最小动作（输一次密码）；完成后跑探针 A/B 与 P50/P95，不与服务级样本混算

## Stop conditions
- 浏览器链路验收数据已在满足凭证绑定的 origin 上以真实链路取得（服务端确认收到 audio/turn，口径=浏览器端到端）
- 确认所有可达 origin 均不满足绑定 ⇒ 停止枚举交互层，转为上报配置矛盾或请求用户动作（登录/改配置）

## Verification
- 最终采样页面的 origin 与配置的凭证绑定域一致，WS 握手以要求的凭证形式成功且服务端日志出现 audio/turn 事件
- 性能样本未混入服务级数据，『已测』与『达标』分开记录

## Counterexamples
- 握手接受 Bearer/query token、与 origin 无关（API-key 直连通道）⇒ 预检立即通过，本地 origin 可直接验收
- cookie 绑定域为空或 host-only（localhost）⇒ 本地链路可用，无需切公网
- 任务目标本身就是验证本地部署语音是否可用 ⇒ 预检结论仍是有效发现（本地不可用+静默断层），但下一步是记录/上报，而不是换 origin 绕开
- UI 已显式弹出握手错误码/错误提示 ⇒ 直接按错误归因，预检不新增信息
