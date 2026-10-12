---
method_id: resolve-tool-precondition-error-via-error-named-registry-4c2def5c2153
name: resolve-tool-precondition-error-via-error-named-registry
description: 工具报出带量化前置条件的错误（required=1, observed=2）时，错误文本本身就是指向权威 registry 的 provenance edge：直接枚举该 registry（如 CDP /json/list）取得实例清单，再用同一协议逐实例查状态，而不是扫进程表或全量读 schema。修复握手失败时优先选不破坏现场的非破坏性等价手段（客户端 suppress_origin），而非按错误字面重启/改 flag——因为现场（登录态、页面状态）往往正是用户目标要验证的对象，重启即销毁证据；自终止型次实例（验证页）可能自行关闭，使绑定问题无需干预即消失。最后用原工具恢复感知做交叉验证后停止。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ca02bdc1-1ca9-4389-9732-e3ba796f5550:48:901dc33c91fcf6e04bb7
evidence_refs: learning:learn:07e55bb62a74
created_at: 2026-10-07T17:23:33.350359+08:00
updated_at: 2026-10-07T17:23:33.350359+08:00
---
## Trigger
工具调用因环境前置条件失败且错误回执自带量化事实（如『must expose exactly one page when target_id is omitted; observed=2』），同时被阻塞的实例本身可能已承载用户目标的结果（如已登录页面）。

## Discriminator
错误回执已当场证明三件事：端点存活、前置条件可精确计数、且存在列出实例的权威 registry（CDP /json/list 类）。因此『浏览器进程在不在跑』『schema 是否支持消歧参数』要么已被错误文本回答、要么是次要未知量；真正未知的只有各实例当前状态——应直查 registry，而不是 ps aux 全量枚举进程。修复指令若需重启环境，字面执行会销毁待验证现场，非破坏性等价手段优先。

## Short path
- 把错误文本解析成前置条件断言（required=1, observed=2），确认这是可枚举的环境状态问题而非工具用法错误
- 沿错误暗示的 registry edge 直接枚举实例（curl /json/list），区分真实 page 实例与 browser_ui 辅助实例
- 逐实例查询前若协议握手被拒（403 origin），采用错误回执内修复指令的等价非破坏手段（客户端 suppress_origin），避免重启环境破坏待验证现场
- 对主实例查询用户目标所需事实（登录 cookie、页面昵称）；对次实例的『No such target』按自终止证据处理，不强行复活
- 前置条件恢复后用原工具重新感知，与直查结果交叉验证后即停

## Stop conditions
- 已从主实例取得用户目标所需权威事实（如登录 cookie 与页面渲染昵称双源一致）
- 原工具在前置条件恢复后能正常感知，且与直查结果一致
- registry 不可达或无权限枚举——此时才升级为环境修复路径

## Verification
- 结论至少两个独立来源交叉：实例内状态查询（cookie/localStorage）+ 页面渲染证据 + 原工具 snapshot
- 确认未发生破坏现场的修复：浏览器未重启、目标实例未被主动关闭（次实例关闭有 no-such-target 回执为证）
- 报告中区分已验证事实与推断（『验证页已完成并自动关闭』标注为基于回执的推断）

## Counterexamples
- 错误是 transient timeout 或明确指向工具自身 bug 的协议错误：不是环境 registry 问题，重试或读工具契约即可，不要枚举实例
- 重启环境代价低且现场无价值（全新抓取任务）：按错误建议加 flag 重启更干净，不应为保现场而绕路
- 工具 schema 本身暴露 target_id 类消歧参数：优先传参绑定目标页，而不是做环境侧枚举
- registry 清单与错误计数不一致且存在多个候选 endpoint：先确认工具实际连接的端点再枚举，避免查错 registry
