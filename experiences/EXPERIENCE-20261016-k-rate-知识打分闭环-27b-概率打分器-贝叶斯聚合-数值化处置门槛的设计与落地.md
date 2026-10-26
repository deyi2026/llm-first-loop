---
title: K-Rate 知识打分闭环：27B 概率打分器 + 贝叶斯聚合 + 数值化处置门槛的设计与落地
scenario: "为 LFL 知识库（method 1084/experience 486/rule 33）建打分系统：需要评分排序索引供其他大模型接入时定加载优先级，低分知识要有\"优化 vs 弃用\"的数值化标准，且 method 池 1051 candidate 只有 1 qualified（生命周期有入口没出口）。scorer 是本地 27B（/v1/systemone，只支持 score/noul/choice，无自由文本）。"
root_cause: ""
solution: 三层闭环：krate_score.py（事件打分）→ krate_index.py（聚合+索引+处置建议，原子写）→ krate_common.py（所有阈值单一真值源）。评分输入=现有 data/methods/usage.jsonl（settlement 已落盘，不用造新数据流）。自评偏置三重控制：evidence_level 权重、borderline 半权、scorer 独立于自报 benefit 交叉验证。处置标准：低分先诊断原因再分流（0档高发=召回错配→改 trigger；E_shrunk 低=降级观察；hindered≥2=失效保留尸体；卡龄>45d=降权不删；hold 后 top≥3=复活）。工具在 tools/krate/，产物在 data/knowledge_index/（index.json/md + dispositions.md）。
evidence: 实测回执：scores.jsonl 4 条 v2 事件全部打分（top/E/p_suff/class 字段完整），幂等重跑返回 no pending；3 条空 note 事件正确落 borderline p_suff 0.36-0.43；method-root-cause 自报 mixed 与 scorer top=2 E=1.68 交叉一致；krate_index.py 输出 1613 条记录（method 1094/experience 486/rule 33）与 architecture_status knowledge_health 对齐；n=1 事件被 n≥3 门槛正确拦截在 MONITOR 未冲 QUALIFY。产物见 data/knowledge_index/index.json header（prompt_hash=9892f9f48ca3）。
tags: [knowledge-scoring, lfl, calibration, ","]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-16T20:57:37.479974+08:00"
updated_at: "2026-10-16T20:57:37.479974+08:00"
---

针对"给知识库打分排序"需求，用 grill_me 两轮拷问暴露 9 个盲点后落地三层架构：①评分层 krate_score.py（事件级打分，p_suff<0.35 不计分、0.35-0.65 半权，submission_hash 幂等，scorer 挂则留 pending 绝不造默认分）②聚合层 krate_index.py（贝叶斯收缩 E_shrunk=(2·2.0+Σw·e)/(2+Σw)，单次满分只到 2.67；evidence_level 加权控自评偏置；卡龄 30d 免衰后线性衰减）③处置建议层（8 种建议映射到原生工具，rule 类强制 RULE_INDEX_ONLY 走 submit_evolution 永不弃用）。当前性验证：cd 仓库根跑 `python3 tools/krate/krate_score.py && python3 tools/krate/krate_index.py` 应得 "no pending events (4 already scored)" 与 "records=1613 rated=4"；`grep -n "submission_hash" tools/krate/krate_score.py` 应命中幂等键逻辑；scorer 依赖 127.0.0.1:8091 在线，挂掉时退出码 2。