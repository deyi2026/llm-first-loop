---
title: 飞书附件不落盘的找回方法 + 矢量PDF转DXF实测（文字轮廓化≠扫描件）
scenario: "用户经飞书发来的 PDF 附件文字提取为空，被误判\"扫描件\"；需要实际检测并转 CAD。附件原始文件未落盘（feishu 链路 process_upload 内存处理后即丢弃）。"
root_cause: "飞书附件经 handlers._handle_file→process_upload 只提取文本注入上下文，原始 bytes 不落盘，事后无法本地重处理；且\"文字提取为空\"被误判为扫描件，实际是矢量 PDF 文字已转轮廓（font=0, Tj=0, 每页 15万+ line 算子）。"
solution: "1) 找回文件: data/audit/feishu_audit.jsonl 里 attachment 记录含 message_id/chat_id → 用 .env 的 FEISHU_APP_ID/SECRET 换 tenant_access_token → GET /im/v1/messages/{mid} 拿 file_key → GET /im/v1/messages/{mid}/resources/{file_key}?type=file 下载原始 bytes；2) 判型: pypdf 统计每页内容流算子（\bl\b/\bc\b/\bre\b/T[jJ]）——line 算子 15万+/页=矢量 CAD 线稿，Tj=0+font=0=文字转轮廓，非扫描；3) 转换: pymupdf get_drawings()→ezdxf（l→LINE, re→LWPOLYLINE, c→SPLINE, qu 注意新版给 Point 无 x0/y0），pt→mm（25.4/72）+ y 翻转，每页一层 PAGE{n}；4) 验证: 回读实体数+BoundingBox（本例 594×420mm=A2）+ matplotlib LineCollection 直渲对比 PDF 渲染图。注意 ezdxf Frontend 渲染 50 万实体会得空白图，勿信。"
evidence: "data/incoming/李妙斯、林锦鹏方案修改-2026.07.24.dxf (539,866 实体回读验证); data/audit/feishu_audit.jsonl message_id=om_x100b66f5361078a4c0780e54e817036; 会话事件 data/event_logs/781367e4*.jsonl seq2143"
tags: [pdf2dxf, feishu-attachment-recovery, pymupdf, ezdxf, vector-pdf, misdiagnosis-fix]
source: {}
status: active
created_at: "2026-09-05T21:35:12.408967+08:00"
updated_at: "2026-09-05T21:35:12.408967+08:00"
---

诊断链: 1) pypdf 逐页统计内容流算子: \bl\b(线)/\bc\b(曲线)/\bre\b(矩形)/T[jJ](文本) + page.images → line=15~22万/页 且 Tj=0 判定"矢量线稿+文字已轮廓化"，非扫描件; 2) 转换: pymupdf get_drawings() 遍历 items, op=='l'→ezdxf add_line, 're'→LWPOLYLINE, 'c'→SPLINE, 'qu'→LWPOLYLINE(注意新版 pymupdf qu 的 it[1] 是 Point 列表, 无 x0/y0 属性); 坐标 x*25.4/72, y 用 page.rect.height-y 翻转; 3) 验证: 回读统计实体数 + BoundingBox 图幅(本例 594x420=A2) + matplotlib LineCollection 直渲对比 PDF 渲染图(ezdxf Frontend 对 50万+实体会渲出空白图, 不可信)。文字轮廓化导致中位线长仅 0.064mm 属正常, CAD 里放大可读。