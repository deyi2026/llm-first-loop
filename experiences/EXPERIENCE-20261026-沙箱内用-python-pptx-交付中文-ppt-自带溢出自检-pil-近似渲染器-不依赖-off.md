---
title: 沙箱内用 python-pptx 交付中文 PPT：自带溢出自检 + PIL 近似渲染器（不依赖 Office）
scenario: "用户要求\"把分析做成 PPT\"这类交付任务，环境无 LibreOffice、Keynote 自动化与 QuickLook 不可用，且需要控制中文排版不溢出不重叠。"
root_cause: ""
solution: python-pptx（装进工作区 .deps 用 PYTHONPATH 隔离）生成 → 自写宽度估算式溢出自检脚本（check_ppt.py）→ 自写 PIL 近似渲染器（render_preview.py）出 PNG 做视觉复核 → 独立子代理审查 → 修订后重生成并重新审查。
evidence: 实测证据：work/cashout-ppt/ 下 build_ppt.py、check_ppt.py、render_preview.py、税收不是主因_A股套现化_vs_美股回购化.pptx（SHA256 bc385f1b0da799956afd31619ec5be660f37769b801b2ba02364bcd8c2860ae5）；check_ppt.py 输出 NO STRUCTURAL OVERFLOW；qlmanage -t 返回 sandbox initialization failed；osascript heredoc 返回 E6_CATASTROPHIC_HARD（here-doc 交给解释器执行）→ 改为写 .scpt/文件再执行/自建渲染器
tags: [pptx, python-pptx, 沙箱, 排版自检, 中文PPT, 交付物]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T08:47:13.196607+08:00"
updated_at: "2026-10-26T08:47:13.196607+08:00"
---

在 macOS 沙箱（仅可写工作区、网络未隔离）里交付中文 PPT 的可行路径：① 依赖隔离：pip3 install --target .deps python-pptx，运行用 PYTHONPATH=.deps python3，避免污染系统 Python；② 渲染验证不可依赖 qlmanage -t（实测 "sandbox initialization failed"）与 osascript heredoc 驱动 Keynote（被 E6 灾难性硬阻断：here-doc 交给解释器执行），改为自写 PIL 近似渲染器读 pptx 形状/表格/图表画 PNG；③ 排版自检脚本按 CJK 全角≈字号、ASCII≈0.53×字号 估算行数与所需高度，标出文本溢出与表格行高不足；④ 标题行数自适应 + 固定边距/行高/字号是控制溢出的关键，卡片正文框高度要按标题实际行数反推；⑤ 图表用 pptx 原生 chart（可编辑），数值单位必须统一（美元折人民币要在图注写明汇率与"仅量级示意"）。产物：~/lfl-workspace/work/cashout-ppt/（build_ppt.py + check_ppt.py + render_preview.py + 15页 pptx）。