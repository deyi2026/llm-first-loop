---
title: 宿主边界代码（CDP 探针/谓词 JS）必须真浏览器 E2E 验收：fake 层测不出协议形状与宿主形状缺陷
scenario: 浏览器宿主边界代码（CDP 探针/页面内谓词 JS/Runtime 协议往返）在 fake/mock ws 层上测试全绿，但从未被真实协议打过：响应键名、DOM 宿主形状、投影层字段差异在 mock 里全部由编写者自己的（错误）假设构成
root_cause: ""
solution: 凡新写 CDP 往返或页面内 JS 谓词，验收必须包含真 Chromium 子进程 E2E（--headless=new --remote-debugging-port=0 起进程、stderr 轮询 DevTools listening 行、playwright connect_over_cdp 拿页、CdpBrowserMutationActuator/ReadOnlyHost 直连），单测只覆盖服务端逻辑；对协议假设（响应形状、宿主形状、投影字段）一律以 E2E 实测为准，发现的字段缺口记录在案、不在功能任务内偷修。失败 verdict 也要可观测（带上 CDP exceptionDetails 描述），unavailable≠settled 必须可区分。
evidence: tests/integration/test_browser_semantic_guard_e2e.py 5 用例（E1-E5）与 tests/integration/test_browser_dispatch_settle_e2e.py 4 用例（E6-E9）真实 Chromium 145 + CDP 全绿；缺陷清单与修复见 docs/DESIGN-20261007-browser-semantic-guard.md M3/M4 行（第 ①②③ 于 M3、第 ④⑤ 于 M4，含修复方式）
tags: [browser, cdp, e2e, testing, protocol-assumptions]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-07T10:37:23.617520+08:00"
updated_at: "2026-10-07T10:37:23.617520+08:00"
---

M2 fake ws 单测全绿后，M3/M4 两轮真 Chromium E2E 首调各抓出协议级缺陷，共 5 个：①DOM.resolveNode 响应顶层键是 object（RemoteObject）而非 node——mock 层按错误建模照样绿；②已删节点悬垂 objectId 仍可 resolve 且几何归零，被误分类为 guard_occluded（可等"遮挡消失"但页面永不复活）→ 探针 JS 需 el.isConnected 精确分流 detach；③guard 豁免放行与真 version match 在回执上无差别 → verdict 必须显式落 exempted/exemption_reason；④谓词 JS 在 document 根节点宿主上 this.ownerDocument===null 直接 raise → view 解析须防御式覆盖 (this.ownerDocument&&this.ownerDocument.defaultView)||this.defaultView||window；⑤真实 CDP capture 投影层 state.visible 缺席（fixture 层有）——断言必须用投影真值（如 state.expanded），不能用 fixture 层才有的字段。共性：CDP 每个往返的响应形状、DOM 宿主形状、fixture 与真实 capture 的字段差，都是 mock 复述不出的外部事实。