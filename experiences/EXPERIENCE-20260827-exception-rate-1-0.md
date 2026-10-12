---
title: 自我评估五维指标口径失真模式：exception_rate 分子带时间窗、分母取当前进程快照轮次，短新会话必然虚高到 1.0
scenario: 手动触发 self_evaluate 返回 exception_rate=1.00（上一次评估 SE-20260820-002 为 0.06），表面上与同期 success_rate=1.00 剧烈矛盾；需判定指标突变是真实质量退化还是统计口径失真后再沉淀对比结论。
root_cause: "SelfEvaluator._metric_exception_rate（evaluator.py L308-325）分数两端口径不一致：分子 = exception_log.jsonl 经 24h 时间窗过滤后的条数（跨多个会话/run，本次实测 16 条）；分母 = _llm_rounds()（L414-423）读当前进程快照 context_usage.llm_rounds（仅本会话 6 轮）。EVO-20260816-f1f73a0d 给四个数据源加了 _time_filter 防历史污染，但独漏 llm_rounds——短新会话一旦评估，分母极小而分子跨会话，比率远超 1 后被 min(value,1.0) 静默截断为 1.00，呈现\"灾难级恶化\"假象。叠加因素：guard_block 类防护性拦截事件与真实失败混计于同一分子。"
solution: 解读 SOP：见到 exception_rate 极端值先查三处再定性——① 读落盘自评条目 sample_size：若很小且窗口内异常计数>分母（如 16/6）即判口径失真而非质量回归；② 对原始 exception_log.jsonl 按 phase/error_type 归类（guard_block=防护拦截属正常运作、llm_call 超时/HTTP=外部网络问题、tool 层错误才指向内部缺陷）；③ delta 对比看趋势而非绝对值。修复方向（已另经 submit_evolution 提交待人工审批）：分母改用同一 24h 窗口的实际 LLM 轮次（append-only 源统计）、note 中保留截断前原始比率、guard_block 单列不并入失败分子。
evidence: "eval:SE-20260827-001-c58d 落盘条目 {\"name\":\"exception_rate\",\"value\":1.0,\"sample_size\":6}；data/audit/exception_log.jsonl 统计 total=182 / 24h 窗口=16 / 最新三条为 2026-08-27 guard_block(CacheGuardBlockedError)；src/llm_loop/introspection/evaluator.py L165（llm_rounds 未过 _time_filter）、L308-325（min 封顶）、L382-412（_time_filter 仅用于分子侧）、L414-423（_llm_rounds 快照读取）；前例 experiences/EXPERIENCE-20260817-llm-call.md"
tags: [自我评估, exception_rate, 指标口径, 根因分析, evaluator]
source: {}
status: active
created_at: "2026-08-27T10:33:43.658240+08:00"
updated_at: "2026-08-27T10:33:43.658240+08:00"
---

实操路径：self_evaluate 异常值 → 不下结论先取证：read_file 读 self_eval_log.jsonl 落盘条目（拿 value/sample_size/source）→ python3 统计 exception_log.jsonl 的全量数、24h 窗口内条数、最新条目的 phase/error_type → 对照 evaluator.py 各指标的窗口过滤调用点（evaluate L161-165）找分子分母口径差。本次链条 5 步内定位根因。注意：search_records(kind=exception_log) 语义检索视图与原始文件不完全同步（检索只见 10 条旧记录，原始文件实有 182 条），归因以原始 jsonl 文件为准。