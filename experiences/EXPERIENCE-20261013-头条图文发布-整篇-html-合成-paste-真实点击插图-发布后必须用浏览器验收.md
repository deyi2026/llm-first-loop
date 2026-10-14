---
title: 头条图文发布：整篇 HTML 合成 paste + 真实点击插图 + 发布后必须用浏览器验收
scenario: 在今日头条创作者后台（profile_v4/graphic/publish，ProseMirror 编辑器）发布图文，需要表格/引用/强调完整还原且含 2 张配图
root_cause: ""
solution: "①正文：清空用 execCommand('delete') 选区全选，标题用 HTMLTextAreaElement 原型 value setter + input 事件；整篇正文 HTML（含表格/引用）通过 DataTransfer(text/html) + ClipboardEvent('paste') 一次性派发，47 段一次成型；平台会把 h2 归一为 H1，属正常。②插图：先 scrollIntoView({block:'center'}) 再用 Input.dispatchMouseEvent 真实点击目标标题行定位光标 → 点 .syl-toolbar-tool.image .syl-toolbar-button（工具栏按钮无 tooltip，只能认 class）→ CDP DOM.setFileInputFiles → 删除 .pic-select-image-item .error 失败项 → 点「确定」。③勾作品声明：label.checkbox-with-tip 内 innerText 为「引用AI」的 input。④发布：「预览并发布」→「确认发布」。⑤验收：作品管理页只能确认「已发布」和展现/阅读；公网正文必须用 Chrome 打开 canonical URL（/item/xxx 会 301 到 /article/xxx）滚动后读 innerText，curl 拿到的是 JS 壳。"
evidence: docs/promotion/receipts/20261013-daily13-toutiao.json（body sha256、6 章节+1 表+2 图公网渲染实见）；STATUS-20261013.md 第 1/3/4/5 条经验
tags: [今日头条, 发布, ProseMirror, CDP, 验收]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T11:37:55.641234+08:00"
updated_at: "2026-10-13T11:37:55.641234+08:00"
supersedes: [EXPERIENCE-20261013-头条图文发布-prosemirror-整篇-html-合成-paste-真实点击插图全链路-含两个实]
---