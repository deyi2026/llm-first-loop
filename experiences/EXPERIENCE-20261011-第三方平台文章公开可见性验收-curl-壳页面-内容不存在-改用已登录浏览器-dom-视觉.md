---
title: 第三方平台文章公开可见性验收：curl 壳页面 ≠ 内容不存在，改用已登录浏览器 DOM+视觉
scenario: 今日头条/知乎等反爬站点的公网单篇可见性验收（curl 返回壳页面、playwright 白名单不含该域名）
root_cause: ""
solution: "1) curl 只用于判断 HTTP 状态码，判正文一律用已登录浏览器；2) 用 browser_perceive 投影 kinds=[\"heading\"] 拿到正文容器 grounding_ref，再 scroll + vision + read_image 逐屏实见；3) 向上滚动不可用 delta_pages 负值，需重新 navigate 重置；4) 验收结论按实见口径写，未实见的项记 gap 不推断通过；5) 截图 SHA256 与回执一起落盘。"
evidence: "2026-10-11 D05 复核：curl 72914B 壳页面 vs 已登录浏览器实见标题/作者/23:56/正文/AI声明；playwright_exec schema 白名单仅 feishu.cn+localhost"
tags: [browser, 验收, 反爬, evidence, toutiao]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-11T09:28:52.517480+08:00"
updated_at: "2026-10-11T09:28:52.517480+08:00"
---

场景：平台文章"提交后状态未知"需要判定是否已公开。curl 拿到的字节数大不代表拿到了正文——、今日头条对非浏览器 UA 返回 HTML 壳（本次 72914 字节、0 个 image_list、无 RENDER_DATA），据此判定"内容不存在"是错的假阴性。playwright_exec 的 goto 白名单只有 feishu.cn/localhost/127.0.0.1，不要指望它做第三方站点验收。有效路径：已登录浏览器 navigate → 等 complete → snapshot(投影 kinds=["heading"] 拿正文容器 grounding_ref) → scroll(容器 grounding_ref) → snapshot(vision=evidence) → read_image。注：delta_pages 负值（向上滚）实测无位移，需 re-navigate 重置滚动位置。