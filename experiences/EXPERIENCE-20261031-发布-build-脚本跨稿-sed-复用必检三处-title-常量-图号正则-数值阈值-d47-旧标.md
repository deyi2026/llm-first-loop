---
title: 发布/BUILD 脚本跨稿 sed 复用必检三处：TITLE 常量、图号正则、数值阈值（d47 旧标题事故，GATE 双保险拦停）
scenario: LFL 头条发布链路 _dXX_publish.py / _dXX_build.py 跨稿复用（sed 派生）
root_cause: sed 批量替换未覆盖全部需随稿更新的常量；VERIFY 的 title_ok 用同一旧常量自比较，自身无法发现 TITLE 错（靠 chars 阈值偶然拦停）
solution: 复用后 grep 核对 TITLE/图号正则/数值阈值三处；MIN_CHARS 按当前稿编辑器实测重设；verify 的 title 校验建议同时比对 md 首行标题而非仅脚本常量
evidence: docs/promotion/STATUS-20261031-daily47.md §五（首次发布尝试 GATE FAIL 拦停记录）与 §六教训第 1 条；verify 回执 chars=2908、title_ok 判定自洽性缺陷说明
tags: [推广, 发布脚本, sed复用, 双保险]
source: {}
status: active
record_kind: lesson
verification_state: unverified
created_at: "2026-10-31T13:45:10.597748+08:00"
updated_at: "2026-10-31T13:45:10.597748+08:00"
---

现象：2026-10-31 午班 d47 从 _d46_publish.py 用 sed 生成发布脚本，只改了图号正则漏改 TITLE 常量（还留着撤稿 ATLAS 稿的旧标题），prepare 把新正文贴进编辑器后 title 阶段把旧标题写了进去；幸 VERIFY GATE 因新稿编辑器字符数 2908 < 沿用 d46 的 MIN_CHARS=3000 判 FAIL 拦停（双保险），关 tab 重来。同日还发生过 sed 漏改 BUILD 输出路径把 d47 HTML 覆盖写入 daily46-paste.html（后用未变的 d46 md 重建恢复）。规则：发布/BUILD 脚本跨稿复用后必须逐一核对三处——①TITLE 常量与当前稿标题一致；②图号正则（图N｜/图N：）与当前图号段一致；③MIN_CHARS 等数值阈值按当前稿实测重设（编辑器 chars≈md 非空白字符×0.94，阈值取实测值−100 左右）。核对方式：grep 三处后 diff 标题串，不靠流程惯性。