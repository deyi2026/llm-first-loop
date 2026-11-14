---
title: 宿主准入 article_publish 逐行比对：markdown 表格行必失配，加粗内 `*` 也会失配；发布前本地用宿主同款函数预判
scenario: 今日头条图文发布链路走 review_admission(kind=article_publish) 时，稿件正文含 markdown 表格，或加粗片段内出现 `*`，宿主会报 manuscript_page_text_mismatch（match_ratio < 0.9）拒绝放行。
root_cause: "宿主实现（src/llm_loop/tools/review_host_admission.py::_comparable_lines + _manuscript_consistency）把 md 逐行剥掉 `*`、`` ` ``、行首标记与多余空白后，要求每行「整行」是页面扁平文本（所有空白折叠成单空格）的子串，未命中率 ≥10% 即拒绝。markdown 表格在页面上被渲染成表格单元格，`| supersed | 1 | 1 |` 这类行文本不会原样出现 → 每行必失配（d83 实测 9 行表格全部失配）；加粗片段内含 `*` 时 md2html 解析后加粗未闭合、页面残留字面 `**`，而宿主侧已剥掉 md 的 `*`，两侧文本不一致 → 该行失配。"
solution: 发布前本地用宿主同款函数预判：import src/llm_loop/tools/review_host_admission.py 的 _comparable_lines/_manuscript_consistency，用「稿件 md + 编辑器 innerText」复算 match_ratio，低于 0.9 就先改稿再送审。修法：①正文里的 markdown 表格改为列表行（数字与词一一对应，不改事实）；②加粗片段内不要出现 `*`（如 `**递归匹配 *.py**` 改为 `**递归匹配所有 .py 文件**`）；③改后重贴编辑器、核对预览抽屉内容与编辑器一致，再跑准入。
evidence: docs/promotion/receipts/d83-admission-fix.json（宿主首次拒绝 match_ratio=0.8906/threshold=0.9）；改后本地同款函数复算 0.9603（126 可比行/121 命中），R5 窄复审 PASS；最终 review_admission(kind=article_publish) PASS（child subagent_37d6e94c335e），发布后公网实见验收全通过（receipts/20261113-daily83-public-verified.json），收口 CLOSEOUT_VERDICT=PASS。
tags: [promotion, review_admission, toutiao, markdown, publishing]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-13T14:37:42.934287+08:00"
updated_at: "2026-11-13T14:37:42.934287+08:00"
supersedes: [EXPERIENCE-20261103-rule28-准入送审稿件-md-markdown-表格会被页面拆成单元格行-必须先改成逐行正文句]
---