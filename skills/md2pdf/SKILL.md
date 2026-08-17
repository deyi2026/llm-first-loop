---
name: md2pdf
description: Markdown 转 PDF 技能（reportlab 方案）——需要把报告/文档转 PDF 发送或存档时使用。pandoc 缺 xelatex/pdflatex、weasyprint 缺 libgobject 系统库时用本方案（脚本 scripts/md2pdf.py 已入库）。支持标题/表格/列表/引用渲染。触发工具: execute_command（描述含工具名才会被经验注入自动提示）。
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
.venv/bin/python scripts/md2pdf.py <in.md> <out.pdf>
```

## 脚本能力
- 标题（# / ##）、表格（| 分隔 + 表头）、列表（-）、引用（>）、正文
- 表格带表头背景 + 网格线，字号 8pt（长表可读）
- A4 页边距 15mm，标题 16/13pt，正文 9pt

## 失败对策
- reportlab 未装 → `.venv/bin/pip install reportlab`
- 表格列太多溢出 → 手动调 FONTSIZE 或缩减列
- 中文乱码 → 需注册 CJK 字体（当前脚本假设英文，中文报告需扩展）
