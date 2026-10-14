---
title: 核对论文图像层内容：用 pymupdf 提取原始嵌入图 + 独立 OCR 引擎交叉验证
scenario: 需要核实论文 PDF 里只有图像/视频层、没有文本层的细节（流程图子任务名、图内标签、被丢弃候选的数字等），纯文本抽取无法覆盖时。
root_cause: "read_image 与人工视觉同属一条通道，多次读取会给出相关性一致的错误转录；且按均分网格猜裁剪坐标会把相邻图元的文字误当作目标标签，产生看似合理实则错误的\"具体细节\"。"
solution: "四步法：(1) 用 pymupdf 定位图块：逐页 get_text 搜 caption 关键词，再用 get_image_info(xrefs=True) 拿每张嵌入图的 xref 与 bbox，按页码+纵向位置确定目标图；(2) extract_image(xref) 导出原始嵌入图（非页面渲染），拿到原生分辨率，避免低 dpi 渲染导致文字不可辨；(3) 关键一步：用与 read_image 不同的独立 OCR 引擎交叉验证——macOS 可 pip install pyobjc-framework-Quartz/Vision 到 venv，VNRecognizeTextRequest 设 recognitionLevel=accurate(0) 且 setUsesLanguageCorrection(False) 保留原始字符，输出 bbox+text+confidence 并按坐标排序，可同时给出内容与版面位置；(4) 需要逐格精读时，裁剪坐标必须来自 OCR/视觉返回的实际坐标，不能用\"均分网格\"假设。本案均分假设把跨排的状态框裁成了标题栏，导致第三轮转录与前两轮冲突；改用 OCR y 坐标后冲突消解。环境注意：系统 python3 受 PEP 668 保护，用 python3 -m venv 建 venv 装 pymupdf/pyobjc；PIL 留在系统 python 即可。"
evidence: "macOS Vision OCR 在 arXiv:2609.32862v1 Figure 6 原始嵌入图(xref 789, 2287x1645)上识别出 14 个文本框且 conf 全为 1.000，明确区分了标题栏(y≈33-37 与 y≈980-983 的六步动作标签)与跨排状态框(y≈721-867 的 01 WRITE/+ funnel_ready、03 WRITE/+ scale_tared、06 READ → ACT/funnel_ready → pour())，与前两次视觉读取在动作标签上一致，并解释了均分裁剪导致的冲突。"
tags: [paper-verification, pdf-image, pymupdf, ocr, cross-validation, hallucination-control]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T15:47:28.242980+08:00"
updated_at: "2026-10-13T15:47:28.242980+08:00"
---

四步法（以 arXiv:2609.32862v1 实际执行通过）：
(1) 定位图块：逐页 pymupdf get_text 搜 caption 关键词定页码，再用 get_image_info(xrefs=True) 列出该页每张嵌入图的 xref/bbox/原始像素，按纵向位置确定目标图；
(2) extract_image(xref) 导出原始嵌入图，避开低 dpi 渲染造成的文字不可辨；
(3) 独立引擎交叉验证：macOS 下 venv 装 pyobjc-framework-Quartz/Vision，VNRecognizeTextRequest 设 recognitionLevel=0(accurate) 且 setUsesLanguageCorrection(False)，取 topCandidates_(1) 的 string/confidence 与 bbox，按 (1-bb.y-h)*H、bb.x*W 换算像素坐标后排序；
(4) 逐格精读的裁剪坐标必须取自 OCR/视觉返回的真实坐标，禁止"均分网格"假设。

本案验证结果：OCR 在 Figure 6 原图上返回 14 个文本框、conf 全 1.000，y≈33-37 与 y≈980-983 是六步动作标题，y≈721-867 是跨排状态框（01 WRITE/+ funnel_ready、03 WRITE/+ scale_tared、06 READ → ACT/funnel_ready → pour()）。动作标签与两次视觉读取一致；均分裁剪曾把状态框误读成"04 WRITE/05 WRITE"，改用 OCR 坐标后冲突消解。

当前性验证：复现命令 `cd /tmp/rf && ./venv/bin/python ocr.py`（脚本与 fig6_raw.png 若仍在）应重新打印同样 14 个文本框；若论文 PDF 更新或 venv 已清理，需按步骤(1)(2)重新导出原图后重跑，不可直接引用本卡缓存结论。