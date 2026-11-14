---
title: 发布前用宿主同款函数本地预演稿件—页面一致性 match_ratio，可省掉一次被拒的宿主准入
scenario: d84 发布前，宿主准入会校验「磁盘稿件正文行是否都在页面可见正文里」，阈值 0.9，失配原因常见为 md 图片行与页面 alt 文本的形态差异、markdown 表格行、加粗内残留字面星号。d83 班曾因此被拒两次（publication_button_not_observed、manuscript_page_text_mismatch）。d84 班在发起 review_admission 之前，先用仓库内宿主同款函数 _comparable_lines / _manuscript_consistency，对 CDP 取到的编辑页 document.body.innerText 复算，得 match_ratio=0.9444（失配 5 行 = 4 条 md 图片行 + 标题行因标题在 input 框、innerText 取不到），高于阈值，准入一次通过。
root_cause: ""
solution: "发布前加一步本地预演：用 CDP 连 127.0.0.1:9229 取编辑页 body.innerText 作为页面文本，直接 import src/llm_loop/tools/review_host_admission.py 的 _comparable_lines 与 _manuscript_consistency 复算 match_ratio，并把失配行逐条打印出来定位；低于 0.9 就先改稿（表格改列表、加粗去字面星号）再发起准入。当前性验证：跑 `.venv/bin/python3 docs/promotion/_d84_precheck.py` 应复算得 match_ratio ≥ 0.9 并落盘 receipts/d84-precheck.json；对照读 src/llm_loop/tools/review_host_admission.py 的 _manuscript_consistency（阈值常量 _MANUSCRIPT_MATCH_RATIO）与第 3419–3427 行的准入调用点。"
evidence: "docs/promotion/_d84_precheck.py 与 docs/promotion/receipts/d84-precheck.json（match_ratio 0.9444 / threshold 0.9 / consistent true / unmatched 5）；src/llm_loop/tools/review_host_admission.py:3339-3388 与 3419-3427；宿主准入回执 docs/promotion/receipts/d84-admission.json（qualification=PASS，child subagent_0c61e93b6dbe）"
tags: [rule28, review_admission, consistency, precheck, publish]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-14T08:32:14.109191+08:00"
updated_at: "2026-11-14T08:32:14.109191+08:00"
supersedes: [EXPERIENCE-20261113-宿主准入-article-publish-逐行比对-markdown-表格行必失配-加粗内-也会失配, EXPERIENCE-20261107-md2html-前配图行必须独占一行-图片行紧跟正文行会被并入同一-p-build-占位符断言必炸]
---