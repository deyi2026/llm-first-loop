---
title: 报告 PDF 规范明晰三件套：md2pdf 升级（###/加粗/图片/页码）+ dot 布局交叉检测 + PIL 图例叠加
scenario: 用户要求把股权架构分析报告及其架构图做得"更规范明晰"，且把工具与方法沉淀进 LFL 镜像。报告 PDF 初次渲染 6.8MB、图有 3 处连线交叉、一致行动人虚线框被 dot 丢弃。
root_cause: "① 旧 scripts/md2pdf.py 只支持 #/## 标题与基础表格，不识别 ###、**加粗**、![图](路径)，PDF 里出现字面 ### 与 **；且无图片嵌入能力。② with_diagram PDF 由临时脚本把 1676×1023 PNG 以裸 RGBA 存了两份（≈6.86MB）——reportlab 直接 Image() 嵌入是压缩的（≈300KB，22 倍差）。③ dot 默认布局让长跨层直连边（自然人→目标公司）产生交叉；cluster 画虚线框与 rank=same 约束冲突时被静默丢弃（warning: already in a rankset）。"
solution: "三件套（均已入库 LFL 镜像 scripts/ + skills/md2pdf/SKILL.md）：1) 升级 md2pdf.py：支持三级标题、**加粗**、图片嵌入（自动等比 175mm + 图注）、表格美化、页脚页码；保持 CLI <in.md> <out.pdf> 兼容，新增 --title/--no-images/--image-filter；多图报告出单图版本用 --image-filter 按文件名关键词过滤。2) scripts/graphviz_layout_check.py：用 `dot -Tplain` 输出全部节点包围盒与连线折线，逐段线段相交检测量化交叉数/节点重叠/连线穿过，目标交叉=0；布局修复手法：同层 {rank=same; ...} + 隐形保序边 [style=invis, weight=100]，cluster 与 rank 冲突时外层无框 cluster 嵌套内层画框 cluster，或直接去掉 cluster 用 PIL 叠加框。3) scripts/graphviz_overlay.py：按 plain 坐标把虚线标注框（如一致行动人）+ 底部图例叠加到 PNG；渲染需 -Gpad=1.2 留边防裁切，--pad 必须与渲染一致，图例格式为 颜色:文字（# 开头会触发 shell 注释，要用引号包整个 --legend）。"
evidence: 2026-08-20 会话实测：股权架构报告 md2pdf 升级后 3 个 PDF 变体（纯文 3 页/含现状图 4 页/含整改图 4 页）渲染正常，图片 1 次嵌入；target 图从 3 交叉降到 0 交叉、0 重叠；PDF 从 6.8MB 降到约 300KB；一致行动人虚线框+图例叠加成功（PIL 像素采样确认金色框 y≈192-416 与图例区域存在）。
tags: [md2pdf, reportlab, PDF, graphviz, dot, 架构图, 布局, 交叉检测, PIL, 图例, 报告]
source: {}
status: active
created_at: "2026-08-20T18:40:00.000000+08:00"
updated_at: "2026-08-20T18:40:00.000000+08:00"
---
