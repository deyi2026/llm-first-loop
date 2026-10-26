---
title: 知乎草稿删除：同一草稿有两个 id，列表 id 删会 404、url 字段 id 才 200；React 确认按钮须 CDP 真实鼠标事件
scenario: 清理知乎草稿箱里残留的受污染旧稿。平台 UI 的「删除」按钮点了、确认弹窗也点了，但刷新后草稿仍在草稿箱里，删除没有生效。
root_cause: 知乎把同一草稿的「列表/删除端点 id」与「正文实体 id」分成两个字段，应用删除路径用的是前者，对该条目返回 404；叠加 React 弹窗按钮对合成 click 不响应，导致 UI 路径彻底无效。
solution: |
  ① 先 GET /api/articles/my_drafts?limit=10&offset=0 读目标草稿：同一条草稿暴露两个标识符——列表 href 与 DELETE /api/articles/{id}/draft 用的是 id 字段（如 2097690125249598200），而 url 字段（如 https://zhuanlan.zhihu.com/p/2097690125249598253）里的 id 才是正文实体 id；用前者删返回 404（平台自身删除路径对这类条目失效），用后者直连同一端点返回 200 并真正删除。② React 组件的「确认」按钮用页内 JS element.click() 只会关掉弹窗、不发请求，必须用 CDP Input.dispatchMouseEvent 派发真实 mousePressed/mouseReleased。③ 动手前先在编辑器页读正文特征（h2 数、表数、正文字数、AI 声明出现次数）与已发表稿逐项比对，确认删的是那一版、且无独有内容。④ 判断是否真删成功，以刷新后的列表 DOM + 列表 API 双重回读为准，不看点击回执。
  当前性验证：知乎改版后先在 https://zhuanlan.zhihu.com/drafts 页 Network.enable 后点一次删除抓当前端点，或跑 `curl -s 'https://zhuanlan.zhihu.com/api/articles/my_drafts?limit=10&offset=0' -H 'Cookie: <浏览器cookie>'` 看目标草稿是否仍同时返回 id 与 url 两字段；复现：DELETE /api/articles/{url 字段 id}/draft 应得 200，且随后 my_drafts 不再含该条。
evidence: "2026-10-25 实跑：UI 删除确认后刷新草稿仍在；Network 抓包见 DELETE https://zhuanlan.zhihu.com/api/articles/2097690125249598200/draft → 404；改用 url 字段 id 2097690125249598253 直连同一端点 → 200；随后 GET my_drafts 首屏不再含该条、草稿箱 13→12 条、已发表文章 https://zhuanlan.zhihu.com/p/2097694420728537150 复核完好（h2=11、表=7、正文 13488 字、AI 声明在位）。删除前证据：草稿编辑器 h2=22、表=14、正文 26968 字、AI 声明 4 处（= 已发表稿的 2 倍）。回执 docs/promotion/receipts/rrsi-zhihu-draft-delete.json"
tags: [zhihu, cdp, draft-delete, network-capture, react]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-25T16:18:03.311153+08:00"
updated_at: "2026-10-25T16:18:03.311153+08:00"
---