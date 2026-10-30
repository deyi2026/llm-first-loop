---
title: 工作区回滚后推广班次开工自检：先用含图样例验证 md2html 工具链完整，再进入写稿
scenario: LFL 推广晚班在经历过 workspace 整体回滚（外部恢复操作把 docs/promotion 回滚到旧版本）后开工：工具脚本被静默退化为旧版（md2html 丢图片规则），历史 STATUS 与编号链全部缺失，平台发布记录与磁盘完全脱节。
root_cause: ""
solution: 班次开工先跑工具链样例自检（含图样例 md → md2html → 断言 html img>0 且 grep 无 ! 残段），再写稿；编号与已发主题以平台列表实见为准，不信磁盘回滚态。
evidence: "evidence：本会话 20:14 execute_command 回执（md2html 转换 tags 输出无 img 键、html-img 0 与 md-img 4 对比）；git reflog 仅剩 8c114428f HEAD@{2026-10-29 14:09:41}；docs/promotion 全目录 mtime Oct 29 14:09；修复后回执 artifact://v1/802083160e8d4ee3b4e50b1e6abe22aa（md2html.py +4 行图片规则）与转换校验 html-img 4==md-img 4"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T20:48:01.370719+08:00"
updated_at: "2026-10-30T20:48:01.370719+08:00"
---

2026-10-30 晚班（sched-e03cf1e8:12）开工时，docs/promotion 在 10-29 14:09 被 workspace 恢复回滚到约 10-14 状态：md2html.py 丢失了独立图片行转换规则（![alt](path) 退化成普通段落被剥链接），10-19 以来全部 STATUS/正文/绘图脚本消失，仅平台侧文章还在。本次靠任务规范里"md 图片数==HTML img 数"计数校验在发布前拦住了零图 HTML（md-img 4 vs html-img 0 如实暴露）；若跳过计数校验，会把零图长文直接投到平台。运作规则：推广班次开工第一步，先用一张含图样例 md 跑 md2html 并断言 img>0 且无 ! 残段，再开始写稿；同时把"工作区可能被外部恢复回滚"当作常态风险，开工先对账磁盘产物日期与平台列表（CDP 抓取），编号（dNN）与已发主题以平台实见为准。