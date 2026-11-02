---
title: 先测量再改：诊断必须以实测数字为前提，否则会修错地方
scenario: 性能/载荷类问题优化前，需要先测准现状再决定改法；凭结构推断直接改导致修错地方或白付成本
root_cause: ""
solution: 提方案先给实测数字（字符/秒/条数/上限），数字推翻假设就改诊断再改代码；量测用一次性脚本按字段统计 json 长度并排序，跑完即弃。
evidence: "2026-11-02 实测：/tmp/measure_status.py 输出 targets 视图 total=3610 字符（services 1688 / stage_facts 562 / audit_summary 509 / deployment 439），in_flight 为空时 +17 → 3627；pytest tests/unit -k \"service_control or service_identity or restart or admission or topology or coordination\" → 673 passed；新增 tests/unit/test_service_status_in_flight.py 6 passed；scripts/check_evo_refs.py 全仓扫描 scanned=4428 files, distinct_refs=226, known=237, 未知 302 处 exit=1。两次误诊的实测反证已写入 docs/development_methodology.md「5. 先测量再改」。"
tags: [measure-first, diagnosis, payload-size, avoid-wrong-fix]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-02T11:30:41.783218+08:00"
updated_at: "2026-11-02T11:30:41.783218+08:00"
---

## 场景
对一个"某个数字异常大"的现象提优化方案，凭结构推断（"载荷里 4 份重复的 barrier 一定是大头"）就动手改代码。

## 2026-11-01~02 两次同型误诊（实测反证）
1. 判称「tree scope 下发 762K 整树材料」。实测：tree 材料仅 129,767 字符；797,380 是「材料+模板」，且 full_test 锚定 origin/main，把 31 个提交/100 文件/11.7k 插入的积压整条冻了进去。按误诊改会去修错的地方（省材料体积），真因是基线锚点。
2. 判称「status 载荷 45K 主因是同一 barrier 在 4 个服务下重复」。实测 targets 视图 3,610 字符，其中 stage_facts 仅 562（16%），折叠收益约 8%。按误诊改是白付工程成本（还牵动消费方 schema）。

## 做法
- 提改动方案时**必须贴当前实测数字**（字符数/秒/条数/上限），没有数字不动代码。
- 测法：写一次性量测脚本（如统计每个字段的 json 长度并按大小排序），跑完即弃；不要靠"看回执感觉大"。
- 数字推翻假设时，先改诊断再改代码；诊断改了往往方案就变了（甚至不该改）。

## 判据
一个"优化建议"若说不出它省下多少（字符/秒/次），它不是建议，是猜想。

## 附带教训
同一轮里还出现过在注释写下不存在的 EVO 编号（凭空引用）。凡写"可溯源"的编号，先查真值源；说不清就先不写编号。