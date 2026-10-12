---
method_id: identity-check-before-reenumeration-1348df6535d1
name: identity-check-before-reenumeration
description: 浏览器快照内容与假设表面矛盾时（预期的目标工件完全缺席，出现的却是账号/登录页家具：语言选择 option、'创建账号'/登录链接、service/continue 参数等），先停止在同一页面上换投影继续枚举，用最廉价的权威探针（页面 URL）解析'当前到底是哪个页面'这一未知量；身份确认后再决定继续找目标还是移交用户。本例中首张快照只有语言 option 列表却被当作'Gmail 噪音'，多花一次宽快照才认出登录页。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a8ca7a5d-9f35-462e-b02e-e13f15ff0023:115:b0a23c69d5263f620053
evidence_refs: learning:learn:56afa201fa48
created_at: 2026-09-20T08:47:32.332294+00:00
updated_at: 2026-09-20T08:47:32.332294+00:00
---
## Trigger
感知快照返回的对象与任务假设的页面/表面不符：预期内容（如邮件列表、目标正文）完全缺席，且出现账号页特征元素（语言选择 option、创建账号/登录链接、continue=目标站参数等）。

## Discriminator
第一张快照的可见对象只有语言 <option> 列表（Русский/తెలుగు/עברית，value ru/te…）且无任何邮件线程工件——该事实当时已与'正在 Gmail 收件箱'直接矛盾，足以把下一步从'换过滤再枚举'缩成'先查页面 URL 解析身份'。（随后出现的'创建账号'链接 href 含 signup?...service=mail&continue=mail.google.com 是同向的更强证据，但非必要。）

## Short path
- 初感知后先比对快照与预期表面：预期工件全缺 + 账号页家具在场 ⇒ 未知量='当前页面是哪个'，暂停在页内继续找目标。
- 用最廉价权威探针解析身份：wait/读取 page URL 谓词。
- URL 显示 accounts.google.com 登录页 ⇒ 停止页内搜索目标邮件；改为安全检查：确认聚焦输入框无用户已输入内容（防覆盖用户操作）。
- 导航到目标站（mail.google.com）并用 URL 谓词等待，观察是否被弹回 signin 页。
- 弹回即会话失效得证：停止一切发现动作，向用户移交（本人登录或转发邮件）。

## Stop conditions
- 页面身份已由 URL/权威标识解析后，不再对同一页面做第二次宽快照或换投影枚举。
- 登录墙/会话失效被 URL 证据确认后，立即停止发现类动作，转入用户移交。
- 快照已直接包含目标内容时，跳过身份检查，直接读取并停止。

## Verification
- '会话失效'结论必须由弹回后的 accounts.google.com/v3/signin URL 证据支撑，不能只凭快照家具间接推断。
- 任何可能改变页面状态的动作（导航/输入）前，确认聚焦输入框无用户已输入值（hydrate 状态无 value）。
- 身份判定与后续动作引用同一 scope/URL 证据链。

## Counterexamples
- 快照属于预期表面但夹带噪音（真收件箱 + 多余隐藏组件）：此时按投影过滤/继续枚举是正确动作；本方法的判别点是'预期工件完全缺失 + 账号页家具在场'，而非'有噪音'。
- 顶层 URL 不可靠的场景（iframe 内嵌、SPA 恒定 URL）：身份需改由文档标题、登录表单结构等其他权威标记解析，不套用'先查 URL'。
- 任务目标本身就是语言或账号设置页：语言 option 是预期内容而非矛盾信号，不应触发本方法。
