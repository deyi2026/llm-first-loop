---
name: md2pdf
description: Markdown 转 PDF 技能（reportlab 方案）——需要把报告/文档转 PDF 发送或存档时使用。pandoc 缺 xelatex/pdflatex、weasyprint 缺 libgobject 系统库时用本方案（脚本 scripts/md2pdf.py 已入库，2026-08-20 升级支持 ### 标题/加粗/图片/页码）。配图报告可结合 graphviz 架构图 + scripts/graphviz_layout_check.py（交叉检测）+ scripts/graphviz_overlay.py（图例/标注框叠加）。常用工具: execute_command。
---
# Markdown → PDF（reportlab 方案）

生成报告 PDF（飞书发送/存档）时，优先试 pandoc，失败用本方案。

## 为什么需要（实测踩坑）
1. ❌ pandoc --pdf-engine=xelatex → `'xelatex' not found`（未装 LaTeX）
2. ❌ pandoc 默认 → `'pdflatex' not found`
3. ❌ weasyprint → `cannot load library 'libgobject-2.0-0'`（macOS 缺系统库）
4. ✅ reportlab 5.0.0（项目 venv 已装）→ 可用

## 用法
```bash
# 基础
.venv/bin/python scripts/md2pdf.py <in.md> <out.pdf>
# 指定 PDF 元数据标题
.venv/bin/python scripts/md2pdf.py <in.md> <out.pdf> --title "报告标题"
# 纯文字版（不嵌图）
.venv/bin/python scripts/md2pdf.py <in.md> <out.pdf> --no-images
# 多图报告只出单图版本（按文件名关键词过滤）
.venv/bin/python scripts/md2pdf.py <in.md> <out.pdf> --image-filter tree
```

## 脚本能力（2026-08-20 升级）
- 标题三级（# / ## / ###）、表格（| 分隔 + 表头）、列表（-）、引用（>）、正文、`---` 分隔线
- **加粗**（`**文本**` → 粗体）、`![图注](path)` 图片嵌入（自动等比缩放至 175mm 宽 + 图注）
- 表格美化：深蓝表头 + 白字 + 网格线 + 斑马纹；A4 页边距 15-16mm；页脚页码
- 图片以压缩 PNG 单次嵌入 —— 重要：此前有报告把 PNG 以裸 RGBA 存两份（1676×1023×4 ≈ 6.8MB），
  改用 reportlab Image 后约 300KB（22 倍缩小）

## 报告配图：架构图（dot）质量链路
需要架构图/股权结构图时（`dot -Tpng` 渲染），三步保证"规范明晰"：
```bash
# ① 渲染 + 导出几何坐标
dot -Tplain -Gpad=1.2 graph.dot > graph.plain
dot -Tpng -Gdpi=200 -Gpad=1.2 graph.dot -o graph.png
# ② 客观质量检测（交叉/重叠/穿过），目标交叉=0
.venv/bin/python scripts/graphviz_layout_check.py graph.dot
# ③ 叠加虚线标注框（如"一致行动人"）+ 底部图例
.venv/bin/python scripts/graphviz_overlay.py graph.png graph.plain out.png \
    --box-nodes ZHAO YANG LI \
    --box-label "一致行动人协议（赵/李/杨，锁定36个月）" \
    --legend "#D8E4F0:自然人 #3E5C8A:公司 #EDE3F5:合伙 #4F8A3C:目标 #F0F0F0:子公司"
```

dot 布局踩坑速查（详见 scripts/graphviz_layout_check.py 头部注释）：
- 长跨层直连边是交叉主因 → 同层 `{rank=same; ...}` + 隐形保序边 `[style=invis, weight=100]`
- 节点同时进 graph 级 rank=same 与 cluster → 被移出 cluster（warning: already in a rankset）
- cluster 画虚线框与 rank 约束冲突时 → 改用无 cluster 布局 + graphviz_overlay.py 叠加框

## 失败对策
- reportlab 未装 → `.venv/bin/pip install reportlab`
- 表格列太多溢出 → 手动调 FONTSIZE 或缩减列
- 中文乱码 → 脚本已注册 CJK 字体（STSong-Light，reportlab 内置 CID 字体）
- 图片嵌入报错 → 确认图片路径相对 md 文件所在目录
