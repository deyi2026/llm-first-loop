---
title: ChatGPT 纯文本围栏渲染致 harvest 误报协议违规（非折叠、非懒渲染）
scenario: "LFL chatgpt-web 传输层：ChatGPT 页面应答轮的协议围栏有时被渲染为纯文本段落（P.TextBase-*）而非 CodeBlock DOM（[data-markdown-copy=\"code-block\"]），observe_latest_code_blocks 采集到 0 块并抛 ChatGPTModelProtocolError，但应答文本实际完整且协议合规。2026-10-11 会话 9a7c8ffd 重排后即命中（lfl-model-0001），此前 lfl-model-0005 回复同样纯文本渲染（连续 2 轮）。"
root_cause: ""
solution: 修复方向（未实施）：在 chatgpt_page.observe_latest_code_blocks（或 chatgpt_transport.exchange 采集侧）增加回退——当最新助手轮解析后 code-block 元素为 0 时，从该轮 innerText 解析字面 ```lfl-model-response 围栏（已观察到 innerText 完整可解析）；解析成功且唯一则按正常协议块处理。
evidence: "evidence://v1/e1df09726870d433316e40200c90a6127266615468e7a2909c885f50bded8796（失败trace上下文）；本会话 CDP 只读取证脚本 /tmp/cdp_lastturn_check.py、cdp_allturns.py、cdp_dom_compare.py、cdp_scroll_test.py 及输出"
tags: [chatgpt-web, page-contract, harvest-fallback, ChatGPTModelProtocolError, plain-text-fence]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-11T15:52:56.405246+08:00"
updated_at: "2026-10-11T15:52:56.405246+08:00"
---

现象：chatgpt-web 引擎 run 终态失败，报 ChatGPTModelProtocolError: "ChatGPT model call must return exactly one lfl-model-response fenced block"（chatgpt_transport.exchange）。页面取证（CDP 9229）：助手应答实际已送达且协议合规（innerText 含完整闭合 ```lfl-model-response 围栏与合法 JSON/tool_calls，如 request_id=lfl-model-0001），但 ChatGPT 渲染器将该回复按纯文本段落渲染（P.TextBase-* 容器），而非 CodeBlock 组件（DIV.CodeBlock-* / [data-markdown-copy="code-block"]）。observe_latest_code_blocks 仅认解析后的 code-block 元素 → 计数 0 → 误报协议违规。已排除两种解释：①视口懒渲染——滚动入视口后 7s 仍不重解析；②"显示更多"折叠——该轮无 expander、文本完整。同会话早前 lfl-model-0005 的回复同样为纯文本渲染（连续 2 轮命中）。
当前性验证：grep -n "observe_latest_code_blocks" src/llm_loop/llm/chatgpt_page.py 确认 harvest 路径当前无 innerText 回退（修复未实施时成立）；修复后复验：grep -n "must return exactly one lfl-model-response" data/web.log 取最后时间戳应早于修复部署时间，且重排会话新 run 无新增该错误。复现：对绑定的 chatgpt.com 页跑 CDP 脚本读最新助手轮父节点，codeBlockEls=0 且 innerText 以 ```lfl-model-response 开头即命中本模式。