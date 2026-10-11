---
title: "经验卡漏检多因检索词按\"任务名\"而非\"失败模式\"构造——应先抽象失败族再检索"
scenario: "同一失败族反复出现时，卡已在库但检索词没命中：09:29:41 用\"头条 发布 图文 草稿 发布按钮\"检索，未命中 EXPERIENCE-20261010-force（该卡讲的是 force 强制点击被系统浮层吞掉，关键词是 force/浮层/遮罩/点击落空），而当日 09:42-09:53 恰好又撞上同一失败族（按钮被覆盖元素挡、rect.y 为负点击静默失效），处置与卡一致但仍重走一轮试错"
root_cause: 检索词以任务名词构造，未以失败模式/症状词构造，导致同族卡不可达；且同日建卡无跨卡交叉引用机制
solution: "1) 检索前先把现象抽象成失败族词（浮层/遮罩/覆盖元素/rect 为负/点击落空/静默失效）而不是任务名词（草稿/发布按钮/图文）；2) 同日建卡时把已知同族旧卡的 stable ref 写进新卡并回溯 record_use，避免\"新卡孤岛\"；3) 发现卡内某一步已失效（如 10-10 卡的\"点第 12 个 toolbar 按钮 → input[type=file]\"今日实测恒为 0）必须就地标注失效范围，而不是另立新卡了事"
evidence: "evidence://v1/90a7456405a9a261b45a3d7e31c3de2423ccfecd95adbea1b16d44ec1c066472（09:29:41 检索词记录）、evidence://v1/e9f6c6da388914e0f4ddc775bf3f476a1c95c56074d05eacea9a3ebac9a3c52f（2026-10-11 三张新卡 frontmatter 无交叉引用字段）、refine_experience 对 experience:EXPERIENCE-20261010-force 的 adapted 回执 note"
tags: [经验检索, 漏检, 失败族, 关键词构造, record_use]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-11T10:32:58.420473+08:00"
updated_at: "2026-10-11T10:32:58.420473+08:00"
---