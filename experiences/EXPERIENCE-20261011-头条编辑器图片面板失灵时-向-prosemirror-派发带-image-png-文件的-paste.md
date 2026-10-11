---
title: 头条编辑器图片面板失灵时：向 ProseMirror 派发带 image/png 文件的 paste 事件完成上传
scenario: 今日头条 ProseMirror 编辑器图片上传面板无响应时的替代注入路径
root_cause: ""
solution: "用 File + DataTransfer + 合成 paste 事件让平台自行上传图片，再读回 CDN 地址组装整篇 HTML；配 scrollTo(0,0) 与元素级 click 规避工具栏/发布按钮的坐标失效。"
evidence: "2026-10-11 D07：面板 0-based 11 号按钮点击后 input[type=file] 始终为 0（连点 7/11/12 均无面板）；改用文件粘贴后 3 张 1200×720 图上传成功，正文 3349 字、发布 PGC 7695222260822491648；回执 receipts/20261011-daily07-submit.json sha256=39c0034990265bf1ffb989c64900c4838373bebc1c86b4ee835ad5e5dda5d1b3"
tags: [toutiao, CDP, 配图, ClipboardEvent, publish]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-11T09:55:41.351025+08:00"
updated_at: "2026-10-11T09:55:41.351025+08:00"
---

今日头条编辑器图片面板无响应时的替代路径：把本地 PNG 转 base64，在页面上构造 `new File([Uint8Array], name, {type:'image/png'})`，塞进 `DataTransfer.items`，再向 `.ProseMirror` 派发 `ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true})`。平台会自行上传并在文档中生成 CDN 图片节点；随后读取 `.ProseMirror img[src]` 即得平台地址。2026-10-11 用该路径成功上传 fig25/26/27 并完成投稿。当前性验证：先 `Runtime.evaluate` 确认 `document.querySelectorAll('.ProseMirror img').length` 增加且新节点 `naturalWidth>0`，再继续下一篇；另注意统计图片数须过滤 `offsetParent!==null`（每张图有隐藏 templ 副本）。