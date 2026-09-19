---
title: 紧急压缩全链路验证通过（修正版）：空检索三误区与判别实验法
scenario: "压测超大载荷触发 glm/glm-5.3 上下文超限（908,715 tokens > 900,000 安全边距），验证「拦截→紧急压缩→可检索找回」全链路；初版经验曾误判「归档可检索性未验证通过」并已归档"
root_cause: 初版误判根因是检索方法错误（长串关键词+对不归档目标检索+检索词不在内容中），非程序缺陷；判别实验（直读档案确认内容存在→短词检索命中）后确认链路正常
solution: 紧急压缩归档链路正常，无需修复。再遇 search_archive 空结果时：①检查是否误搜了 architecture_status 截断内容（该类不归档）；②改用落盘档案中确定存在的短关键词重试一次；③仍空才考虑按 RULE 11.2 上报，上报前必须先 read_file 直读档案做判别实验
evidence: "search_archive('calib') 命中回执（原文含 run.compact 帧与 glm-5.3 预算轨迹）；ls 确认 data/archives/fb8f8987-14c0-4d31-bfc9-78b88cdfc869.jsonl(+.idx) mtime=Aug 26 22:58；read_file 档案首行含被压缩 architecture_status 全文"
tags: [上下文超限, 紧急压缩, search_archive, 短关键词, 判别实验, 误判修正, RULE-11.1]
source:
  model: glm/glm-5.3
  rules: ai_rules.lite.md v4 RULE 11.1/11.2
  session_archive: data/archives/fb8f8987-14c0-4d31-bfc9-78b88cdfc869.jsonl
status: archived
created_at: "2026-08-26T23:02:12.032847+08:00"
updated_at: "2026-09-06T00:16:22.443906+08:00"
promoted_to_rule: RULE-AI-11.1
---

修正版结论（取代 EXPERIENCE-20260826-glm-5-3.md 已归档的错误结论「归档可检索性未验证通过」）：
1. 全链路验证通过：守卫拦截（908,715 tokens 超安全边距 900,000，未发送必失败请求）→ 自动紧急压缩（run.compact，档案落盘 data/archives/fb8f8987-....jsonl + .idx 索引，mtime 与压缩时刻一致）→ 下轮请求正常处理 → search_archive('calib') 命中取回被压缩原文（含 run.compact 告警帧、glm/glm-5.3 1000000→300000 预算轨迹、calib 校准数据）。「信息零丢失可检索找回」承诺兑现，无程序缺陷。
2. 之前误判的三个检索方法错误（按 ai_rules.lite.md v4 RULE 11.1）：
   ① search_archive 用多词长串（'qwen3.8-27b-mlx LM Studio decode 18 tok/s'）——规则明确要求短关键词；
   ② 对 architecture_status 截断内容做 search_archive——规则明确该类截断「不落盘不归档，只能 dimensions 缩小查询」；
   ③ 搜 'qwen' 空结果误当脱节证据——qwen 事实在 [[memory]]，不在被压缩的这条 tool 结果里，空结果是正确行为。
3. 判别实验方法：验证「可检索找回」类承诺时，先 read_file 直读落盘档案确认目标内容真实存在，再用该内容中的确定存在的短词（如 calib）做检索测试——命中即闭环；空检索可能是「内容本不在目标里」（正确行为）而非「检索脱节」（缺陷），判别实验前不可下缺陷结论。
4. 附：save_experience 同日同主题会 slug 冲突（不覆盖保护），换 title 主题词即可。

## 2026-09-06 lifecycle review

该经验的“三种截断判别 + search_archive 短关键词 + 未命中后不重复空耗”已经直接升格为当前 `docs/ai_rules.md` RULE-AI-11.1；经验保留为来源案例，不再与正式规则形成双权威。
