---
title: 信息图横向多卡布局：溢出被邻卡背景遮挡时全图 OCR 误报可读，必须裁片复核
scenario: PIL 信息图绘制（_draw.py canvas 1000 宽，多列圆角卡片布局）+ read_image 排版验证
root_cause: ""
solution: 横向多卡布局逐卡核算条形/标签坐标（卡片右边界−边距）；排版验证流程：全图 read_image 粗筛 → 对每个疑似溢出/贴边区域裁片放大 read_image 精查 → 以裁片结论为准。当前性验证：跑 python3 docs/promotion/figures/_d35.py 后裁任一卡的右边界带（卡片右界±30px）read_image 应无文字截断。
evidence: "2026-10-24 daily-35 fig152 实测：首版左卡条形底 (ux+110+240)=422 超出卡片右界 336、中卡条形右端 687 超出 646；全图 read_image 报「四条数据完整、25.4% 可读但贴边」，裁片 (350,180,950,470) 复核暴露「右端被净增益账卡片遮挡/截断，右卡左上有溢出残影」；重排（名称+数值同行、条形独立行、scale=244/30 与 244/80 收进卡内）后裁片复核全部完整。对照 d34 纵向高度累计教训（EXPERIENCE-20261021-draw-py）为横向版。"
tags: [draw-py, figures, read-image, layout-verification, clipping]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-24T14:11:48.988159+08:00"
updated_at: "2026-10-24T14:11:48.988159+08:00"
---

信息图多卡片布局中，卡片内条形图/数值标签若横向坐标超出本卡右边界，会绘制到相邻卡片区域并被其不透明背景矩形（SOFT 填充）覆盖；全图 read_image 审排版时 OCR 仍可能把被遮挡内容「读出来」并误报为可读可辨（实测：fig152 中卡条形溢出右卡 19-45px，全图 OCR 列出全部数值且报「可读，紧贴边缘」；裁片放大复核才发现溢出区被邻卡背景遮死）。教训：(1) 横向多卡布局的条形末端 x、数值标签起点 x 必须逐卡按「卡片右边界−安全边距」核算，与纵向累计高度核算同等强制；(2) 排版验证对「疑似溢出/贴边」区域必须裁片单独 read_image，不能采信全图 OCR 的可读判断。当前性验证：grep -n 'bx0\|sc0' docs/promotion/figures/_d35.py 应见条形坐标以卡片内宽度（244px）为 scale 基准。