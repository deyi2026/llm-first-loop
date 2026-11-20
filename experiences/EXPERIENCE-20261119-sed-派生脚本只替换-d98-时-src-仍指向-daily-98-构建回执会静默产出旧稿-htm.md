---
title: sed 派生脚本只替换 d98 时 SRC 仍指向 daily-98，构建回执会静默产出旧稿 HTML
scenario: "LFL 推广：用 sed 's/d98/d99/g' 从 _d98_build.py 派生 _d99_build.py 时，脚本里的稿件路径是 \"20261119-lfl-daily-98.md\"（daily-98 字样不含 d98），未被替换；build 脚本照常 PASS，但产出的是早班旧稿的 paste HTML 与 md_sha256——如果只看 BUILD GATE PASS 会漏掉。"
root_cause: ""
solution: 派生后必须逐项 grep 断言：grep -n 'SRC = |OUT_HTML = |OUT_JSON = ' 新脚本，确认指向本班稿件；并核对 build 回执里的 md_sha256 与当前主稿 sha256 一致（不一致即说明喂错了稿）。当前性验证：跑 python3 docs/promotion/_d99_build.py 后，比对 receipts/d99-build.json 的 md_sha256 与 sha256sum docs/promotion/20261119-lfl-daily-99.md，两者必须相等。
evidence: "回执 evidence://v1/0924fdc4df2c76de5e07680b8c78b04ca35fe7a2f67a3d0f0bcb6a55c95e15f（首次派生后 BUILD 回执显示 SRC=20261119-lfl-daily-98.md、title 为早班标题）；修正后回执 evidence://v1/5e94d150dd68b4a29ebc4a1ca55f2fd7c06e243c2a441dedb6f47dcd0b8b1e2（md_sha256=285676ad… 与本班主稿一致）。"
tags: [推广, sed, 派生脚本, 防退化]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-19T16:55:45.700392+08:00"
updated_at: "2026-11-19T16:55:45.700392+08:00"
supersedes: [EXPERIENCE-20261117-跨篇派生的发布-验收脚本必须清掉上一班的写死值-ui-探针-期数篇号-正文探针一律改为从主稿派生, EXPERIENCE-20261112-派生稿级脚本时-sed-替换覆盖不全-daily-nn-fignnn-pgc-id-首跑收口-fai]
---