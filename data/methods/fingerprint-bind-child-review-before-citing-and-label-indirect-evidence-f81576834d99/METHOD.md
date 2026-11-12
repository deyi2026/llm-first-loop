---
method_id: fingerprint-bind-child-review-before-citing-and-label-indirect-evidence-f81576834d99
name: fingerprint-bind-child-review-before-citing-and-label-indirect-evidence
description: 门禁终态回执只含资格字段（qualification/artifact_reviewed/candidate_sha256）而任务要求核验真实 reviewer 的 VERDICT、P0/P1/P2、实际模型时：按 child_id 取一次原始结果后，先做指纹绑定——结论块回显的 fingerprint 与已获知的 candidate_sha256 做前缀比对，绑定成立才把该结论采信为本候选的裁决；至多用一条第二只读通道（如租约结算）佐证 child 终态；仍无任何通道供应的字段，用 attempts=0、无 fallback 重试、deadline 内完成等间接证据标注'间接支持'，报告逐字段区分直接核验/间接支持/不可核验，防止把子代理结论错误归属或把推断说成确认。
aliases: 审的到底是不是同一个候选, 指纹前缀和候选SHA比对, 模型身份只能间接证实怎么说, 终态回执缺裁决字段去哪补, 把子代理结论绑定到冻结SHA, 交叉佐证只取一条就停
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:96698f07-e135-442b-a866-31d334086a55:0:a010956b7f0c17b08e14
evidence_refs: learning:learn:f64a88f6a448
created_at: 2026-11-12T17:20:34.633868+08:00
updated_at: 2026-11-12T17:20:34.633868+08:00
---
## Trigger
异步审查/准入闸取得非 pending 终态（如 PASS），但用户/任务书要求报告的 reviewer VERDICT、严重级别计数、真实模型名等字段不在终态回执中，需从 child 原始结果补齐并交叉印证时。

## Discriminator
child 原始结果的结论块是否回显 fingerprint/SHA，且其前缀与 start/终态回执中已知的 candidate_sha256 逐字符一致（绑定成立）；以及回执中的 attempts/fallback 计数是否为 0（只能作模型身份的间接证据，不是确认）。

## Short path
- 终态回执非 pending：立即退出轮询循环，缺失字段不改变循环继续条件
- 按 child_id 取一次 child 原始结果，解决未知量：VERDICT 与 P0/P1/P2 原文
- 把结论块回显的 fingerprint 与已知 candidate_sha256 前缀比对，解决未知量：该结论是否属于本冻结候选
- 至多一条第二只读通道（如租约 settlement/outcome）佐证 child 终态，不再追加确认性读取
- 无通道供应的字段（如实际模型名）：以 attempts=0、无 fallback、deadline 内完成为间接证据，明示不可直接确认
- 报告逐字段标注直接核验/间接支持/不可核验后收口

## Stop conditions
- 每个要求报告的字段要么已完成绑定核验，要么已如实标注不可核验
- fingerprint 与 candidate_sha256 前缀不一致：停止采信该结论，转回执冲突归因（转录层 vs 内容层），不继续抓取更多通道

## Verification
- fingerprint 前 16 hex 与 candidate_sha256 前 16 hex 逐字符一致
- 第二通道的 outcome 与 child 原始结果的 child_state 一致
- 报告中不存在把间接证据（如 attempts=0）表述为直接确认的措辞

## Counterexamples
- child 结论块不回显任何 fingerprint/SHA：无法从内容建立绑定，只能依赖 Host 回执的 child↔候选链接，勿臆造匹配
- 门禁终态为 REVISE 而内容计数 PASS：属回执冲突归因场景，不适用本卡的佐证收口路径
- 终态回执已直接包含 VERDICT 与计数：跳过 child 结果获取与绑定层，避免多余抓取
- 同步即时审查无异步 child：直接以回执为唯一权威，无需交叉佐证
