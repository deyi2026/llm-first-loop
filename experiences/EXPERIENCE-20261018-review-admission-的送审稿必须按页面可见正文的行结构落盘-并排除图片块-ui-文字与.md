---
title: review_admission 的送审稿必须按页面可见正文的行结构落盘，并排除图片块 UI 文字与列表渲染序号
scenario: 用 review_admission(article_publish + manuscript_path) 审查头条图文长文：Host 要求稿件正文行与页面可见正文一致，且必须先在页面上观察到发布按钮
root_cause: ""
solution: "送审稿落盘步骤：① 粘贴后从编辑器按块级取 innerText（跳过含 img 的块，剔除图片块\"编辑/搜图\"UI 文字）；② 去掉孤立数字行（有序列表渲染序号）；③ 用 difflib 断言页面文本与转换产物除列表序号外逐字相同；④ 以该行结构写盘作为送审稿，Host 逐行子串匹配即可过 0.9 阈值。审查须排在预览弹窗打开之后，闸门挂在 confirm 上。当前性验证：grep -n \"_MANUSCRIPT_MATCH_RATIO\|_PUBLISH_LABEL_RE\|def _manuscript_consistency\" src/llm_loop/tools/review_host_admission.py 确认阈值与标签正则仍在；并在编辑器页执行 document.querySelectorAll('button').length 观察\"确认发布\"按钮是否仍只在预览弹窗中出现。"
evidence: "2026-10-18 实测：src/llm_loop/tools/review_host_admission.py:676 _manuscript_consistency 逐行子串匹配、阈值 _MANUSCRIPT_MATCH_RATIO=0.9、_comparable_lines 长度≥8；首次按源侧 HTML 行落盘（140 行）与页面 186 行粒度不一致，改为按页面块级行落盘并剔除图片块\"编辑/搜图\"文本后 164 行通过。另实测 target_name 必须是 _PUBLISH_LABEL_RE 精确标签（\"确认发布\"），否则 publication_target_name_required；页面上未观察到发布按钮时返回 publication_button_not_observed（该按钮只在预览弹窗里）。"
tags: [review_admission, toutiao, publish, manuscript, verification]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-18T22:51:07.736607+08:00"
updated_at: "2026-10-18T22:51:07.736607+08:00"
---