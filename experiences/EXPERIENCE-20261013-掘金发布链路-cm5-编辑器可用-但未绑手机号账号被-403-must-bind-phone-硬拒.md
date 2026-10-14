---
title: "掘金发布链路全通：CM5 编辑器+发布面板可用；未绑手机号 403 硬拒（已解）；标签三坑（同名分类 disabled/分类 li 误点/输入残留文字骗过面板文本）"
scenario: 向掘金（juejin.cn）网页版编辑器自动发布 markdown 文章（CDP 直连已登录会话）
root_cause: ""
solution: "1) health probe：灌一句 # hello 看 article_draft/create 响应；403 must bind phone → blocked 转人工。2) 绑手机后重跑：fill（CM5 setValue + title-input native setter，draft 创建成功后 URL 从 new?v=2 变 drafts/<id>）→ 打开发布面板 → 分类点叶子节点 → 标签 byte-select → 确定并发布 → 跳 /published。3) 标签验收唯一可信信号是 select 内 .byte-tag 芯片列表；面板 innerText 含输入框残留文字会假报已选。"
evidence: "2026-10-14 发布成功 https://juejin.cn/post/7696005650718998571（5/5 关键句公网回读命中，article_len 5575）；receipts/20261013-prefix-cache-juejin.json；此前 403 记录：api.juejin.cn/content_api/v1/article_draft/create → err_no 403 must bind phone"
tags: [juejin, publish, cdp, must-bind-phone, markdown-editor, byte-select, tag-picker]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T23:55:06.719894+08:00"
updated_at: "2026-10-14T00:12:00+08:00"
---

编辑器：juejin.cn/editor/drafts/new?v=2 为 CodeMirror5 markdown 编辑器：document.querySelector('.CodeMirror').CodeMirror.setValue(md) 灌正文（去 h1 标题行，标题填 input.title-input 用 native setter+input 事件）。点"发布"开右侧发布面板（切换式：已开时再点会关闭）。面板=分类单选(后端/前端/Android/iOS/人工智能/开发工具/代码人生/阅读)+标签 byte-select(面板内第 1 个)+封面/专栏/话题可选+编辑摘要 0/100+「确定并发布」。

账号门槛：未绑手机号时 article_draft/create 返回 err_no=403 "must bind phone"，草稿无法保存；预览面板永远"出现错误"（哪怕正文只是 # hello），点「确定并发布」连请求都不发——症状极像内容问题，实为账号权限。诊断捷径：先 fetch/XHR 钩子抓 content_api 响应体。绑定手机需真人操作；绑后重跑同链路即通（draft 创建成功，URL 变 editor/drafts/<draft_id>）。

标签三坑（2026-10-14 实跑验证）：
1. 通用 li/[class*=option] 选择器去点标签选项时，会先命中面板里的分类单选项（分类"人工智能"也是 li 且 DOM 在前）→ 返回 PICKED 但实际点的是分类，假成功；必须排除发布面板内的元素、只点 body 端 portal 下拉。
2. 与分类同名的标签选项为 --disabled（点了无任何效果、无报错）：选了分类"人工智能"后标签"人工智能"不可加，实际 tags=[LLM]+category=人工智能 语义等价即可收货。
3. 标签输入框 typed 文本会留在 select 的 innerText 里，面板文本读起来像"芯片已存在"；唯一可信状态是 select 内 .byte-tag 芯片列表（nodeList→innerText）。

其他：发布成功跳 /published（不是 /post/<id>）；正式 article_id 用 api.juejin.cn/content_api/v1/article/query_list（POST，page 上下文 fetch credentials include，注意响应字段是 article_info.title 而非 title_info）查，再拼 juejin.cn/post/<id> 做公网回读。写 CDP 脚本时 JS 里 const 变量重赋值会在 Runtime.evaluate 抛 TypeError 中断脚本（本例 DLG_STATE 就因此崩掉，FINAL 没点成）。
