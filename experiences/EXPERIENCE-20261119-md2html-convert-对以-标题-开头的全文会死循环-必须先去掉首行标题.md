---
title: "md2html.convert 对以「# 标题」开头的全文会死循环，必须先去掉首行标题"
scenario: "LFL 推广班次需要为宿主 RULE-AI-28 审稿单独产出「纯 HTML」产物（md2html 直接转换、不含 data-URI 内嵌图）。本班沿用上一班脚本 md2html.convert(md) 传入整篇 md（含首行「# 标题」），脚本两次超过 60s 超时未返回，而同一篇稿件用 build 脚本的 convert(body)（body = md.split(\"\n\",1)[1]，已去掉首行标题）却在数秒内完成。"
root_cause: ""
solution: "转换前必须先去掉首行标题行：body = md.split(\"\n\", 1)[1]，再 md2html.convert(body)。根因在 md2html.convert 的第 65 行兜底 while：它用 ^(#{1,3}\s|...) 排除以「# 标题」开头的行，于是这一行既进不了 h1/h2 分支，也进不了兜底分支，buf 为空且 i 不推进，形成死循环。md2html.py 的 __main__ 入口本身已做 split(\"\n\",1)[1]，所以命令行路径安全，只有库调用者会踩。另注：md2html 不解析 markdown 图片语法，直接转换后 img 数为 0，图注文案以普通段落形式出现在 HTML 里——审稿材料要含图注时应以 md 为准。当前性验证：grep -n 'lines\[i\].strip() and not re.match' docs/promotion/md2html.py 应命中第 65 行；复现：python3 -c \"import sys; sys.path.insert(0,'docs/promotion'); import md2html; md2html.convert('# T\n\n正文\n')\" 会挂住不返回，去掉首行标题后同函数秒级返回。"
evidence: "本班实测（2026-11-19 08:2x–08:3x）：docs/promotion/receipts/d98research/_d98_plain_html.py 用 md2html.convert(md) 两次触发 execute_command 60s 超时（含后台任务同样不返回）；改为 convert(md.split(chr(10),1)[1]) 后同分钟返回 {\"chars\": 6015, \"img_count\": 0}。对照 docs/promotion/_d98_build.py（convert(body)，body 已去首行）数秒内完成 BUILD GATE PASS。回执：docs/promotion/receipts/d98-build.json。"
tags: [promotion, md2html, deadlock, article_publish]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-19T08:47:59.254847+08:00"
updated_at: "2026-11-19T08:47:59.254847+08:00"
---