---
title: 今日头条移动页正文抓取最短路径：curl 直取 HTML + 解析 RENDER_DATA
scenario: web_fetch 抓今日头条（m.toutiao.com 或 www.toutiao.com 文章页）只返回 JS 壳或失败，需要文章正文
root_cause: 今日头条移动页对常规抓取返回 JS 壳/反爬（httpx 只取到壳，curl 回退也可能被 UA 拒绝），但 HTML 内嵌 RENDER_DATA JSON 含完整正文，直接解析即可，不必等 JS 渲染。
solution: "一条命令路径：① curl -L -sS --max-time 20 -A 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36' '<url>' -o /tmp/xx.html（可拿到完整 HTML，含 HTTP 200）；② python3 解析 HTML 中 <script id=\"RENDER_DATA\" type=\"application/json\">...</script>（内容是 URL 编码 JSON，unquote 后取 articleInfo.content，即正文 HTML，约 9479 字符级）；③ 用 HTMLParser 清洗 <p>/<h1>/<pre>/<code>/<img> 等标签为纯文本。全程无需浏览器渲染、无需 trafilatura（环境常缺）。"
evidence: 2026-08-16 会话：web_fetch 两次失败（httpx 壳/curl 回退失败）后，用本路径一次成功拿到《DeepSeek 开源 Harness 架构拆解与 SaaS 团队冲击》全文（articleInfo.content=9479 字符），并清洗出 5839 字符纯文本。
tags: [抓取, 今日头条, RENDER_DATA, curl, python3, 最短路径]
source: {}
status: active
created_at: "2026-08-16T22:05:08.063379+08:00"
updated_at: "2026-08-16T22:05:08.063379+08:00"
---