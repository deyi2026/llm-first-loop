---
title: 推广配图-图号必须按正文插入顺序递增-粘贴后由编辑器回读图注顺序暴露
scenario: "新稿 4 张图按\"内容重要性\"编号：第六节的\"日常入口\"编为 fig216、第七节的\"LFL 指令入口\"编为 fig215，导致正文文档顺序上的图号不递增。"
root_cause: 图号按内容逻辑而非文档位置分配；正文与配图两套编号没有交叉校验环节。
solution: 配图编号必须按正文出现顺序分配，而非按绘制/思考顺序。粘贴后用编辑器回读的 caption_heads 顺序核对（图213/214/216/215 即为反例），必要时改文件名并同步正文图注与路径，然后重做 paste。
evidence: docs/promotion/receipts/daily49-toutiao-local.json（STATE_AFTER caption_heads 顺序 213/214/216/215 暴露问题）；docs/promotion/img/ 改名记录
tags: [推广, 配图, 图注, 发布链路]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-01T08:43:38.445609+08:00"
updated_at: "2026-11-01T08:43:38.445609+08:00"
---