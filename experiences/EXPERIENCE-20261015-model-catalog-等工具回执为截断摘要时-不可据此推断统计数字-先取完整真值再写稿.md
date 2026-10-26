---
title: model_catalog 等工具回执为截断摘要时，不可据此推断统计数字（先取完整真值再写稿）
scenario: 写科普/技术文章时，从工具回执（如 model_catalog、list_evidence、search_files）里读取统计数字（模型总数、档位分布、上下文窗口等）直接写进正文。
root_cause: 把工具的截断投影（excerpt + projection_complete=false）当成完整结果；且未对派生统计做独立复核。
solution: |
  回执标记 projection_complete=false / representation=excerpt 时，说明是截断投影，绝不能据此推断总数与分布。
  正确做法：用权威路径独立重取真值。本例中用
    python3 -c "import sys;sys.path.insert(0,'src');from llm_loop.config import Settings;from llm_loop.llm.providers import load_registry;reg=load_registry(Settings(llm_api_key='x',llm_base_url='http://x',llm_model='x'))"
  再遍历 reg.providers[*].models 统计 count / cost_tier / context_window / reasoning_control。
  真值（2026-10-14）：28 个模型、5 接入方、档位 free4/low7/mid9/high8、上下文含 65536/192000/200000/256000/512000/960000/1000000。
  此前据截断摘要误推"15 个模型"，被独立审查判 P1 并全量返工。
evidence: "evidence://v1/fac0323370d85c9b82fcea0be1f970aa4a12baffdd4ddee173763d490a45e12c（独立重取真值：28 模型/4-7-9-8 档）；evidence://v1/f4280f839af413b0dc77c7c31f0df329a815773d17988ea0f6f844830eadc84c（首轮审查 FAIL，列 6 条 P1）"
tags: [证据纪律, 截断投影, 事实核查, 科普写作, model_catalog]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-15T00:41:30.618933+08:00"
updated_at: "2026-10-15T00:41:30.618933+08:00"
---