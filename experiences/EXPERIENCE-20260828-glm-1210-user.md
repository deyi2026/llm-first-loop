---
title: 智谱 GLM 1210 根因：尾部连续多条 user 触发结构校验（聚合可修复）
scenario: Agent 运行时对智谱 GLM 端点（OpenAI 兼容协议）的长会话请求在 cache_compact 压缩后首请求稳定收到 HTTP 400 code=1210「API 调用参数有误」。压缩产物帧（归档摘要/关键事实/压缩声明等）以多条连续 user 角色追加在消息尾部。
root_cause: ""
solution: 将尾部连续 user 群（压缩帧+注入）聚合为单条 user（内容逐字保留、分隔符分节）后重发；或从源头避免连续 user 结构。重放验证：原样=400/1210，聚合后=200。
evidence: "evidence://v1/139e347f8fe53709b54ffa31cc9eff58b16ac7761760c4867c47e2efe535fc20"
tags: [glm, 1210, 连续user, 压缩, 聚合重试, err1210]
source: {}
status: archived
created_at: "2026-08-28T03:07:15.429943+08:00"
updated_at: "2026-09-06T00:09:26.141519+08:00"
superseded_by: "experience:EXPERIENCE-20260906-err1210-current-tail-user-contract"
---

## 根因（实验实锤，2026-08-28）

智谱 GLM 兼容端点（open.bigmodel.cn/api/coding/paas/v4，glm-5.3）对**尾部连续多条 user 角色消息**做结构校验，触发 1210。证据：快照原样重放复现 400/1210（0.5s 拒绝）；仅将尾部 6 条 user 合并为 1 条（内容逐字保留、=分隔符分节）后 HTTP 200 正常响应（tool_calls 正常、80404 tokens）。单变量对照，内容无关性证明。

## 触发形态

compact 压缩后首请求的尾部构成：压缩产物帧（归档摘要/关键事实/档案目录/压缩声明/中段折叠/Evidence Manifest）4-6 条连续 user + 可选注入槽（interop/tip/hotcard/gate_note）。chars 恒定模式 252/116/85 可作指纹。

## 修复方案（已验证）

尾部连续 user 群聚合为单条 user（逐字保留、分隔符分节）后重发。非剥离（压缩帧含语义不能丢）、非内容修改。

## 踩坑记录

- err1210 P0 初版只剥离「登记的注入槽」，压缩帧不在登记 → 8/8 次剥离校验失败放弃降级 → 形同虚设
- LFL_DATA_DIR 跨区污染会让观测数据互写对区，排障时先确认数据落点
- offending_payloads 快照是排障金矿：8 个完整载荷使单变量重放实验成为可能
