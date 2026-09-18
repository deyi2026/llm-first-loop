---
title: PDF 附件解析完整链路：venv 绕 PEP668 + pymupdf 渲染 + read_image 视觉转录兜底
scenario: 收到 PDF 附件需要读内容时：① 先用 find/ls 定位文件落盘（可能在 ~/Desktop、~/Downloads、/tmp）；② read_file 直接读二进制无效、read_image 不支持 PDF；③ 需自行打通解析链路。
root_cause: "旧记忆\"本环境无 PDF 解析工具\"在环境演进后过时；macOS 系统 Python 受 PEP 668 保护，直接 pip install 被拒；ProcessOn/扫描件导出 PDF 常无文字层，需视觉转录兜底。"
solution: "PDF 解析三步法：① 定位文件：find ~/Desktop ~/Downloads /tmp -iname \"*.pdf\" -newermt 日期；② 建临时 venv 装解析库（python3 -m venv /tmp/pdfenv && /tmp/pdfenv/bin/pip install pypdf pymupdf）绕开 PEP 668，不污染系统；③ 先用 pypdf 提取文字层（含则直接分析），文字层为 0 则用 pymupdf 渲染 PNG（dpi=200，超大字图用 150-200）再 read_image 视觉识别（prompt 要求按结构逐项列比例、验证合计 100%）。注意：识别结果对数字要交叉核验（比例合计、与既有记忆对照），防止视觉模型误读。"
evidence: 实测链路（2026-08-20）：~/Desktop/202608股权架构方案.pdf（ProcessOn 导出、1 页、文字层 0 字符）→ python3 -m venv /tmp/pdfenv（绕开 PEP 668 externally-managed-environment）→ pip install pypdf 6.16.1（探测文字层）→ pip install pymupdf（fitz 渲染 dpi=200 → 12100×8017 PNG）→ read_image 识别成功，内容与记忆沉淀一致。
tags: [PDF, 附件解析, pymupdf, pypdf, venv, PEP668, 视觉识别, read_image]
source: {}
status: active
created_at: "2026-08-20T17:19:44.202258+08:00"
updated_at: "2026-08-20T17:19:44.202258+08:00"
---