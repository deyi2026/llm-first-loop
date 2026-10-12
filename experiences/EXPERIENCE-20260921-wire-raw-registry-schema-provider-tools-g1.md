---
title: 同源断言要锚到 wire 序列化层：raw registry schema ≠ provider tools 格式（G1 缝隙）
scenario: "hev0 P3 Stage-A 二跑（run 012806Z）：环境修复后 3 个 b0 行全灭于新故障——终态 provider_error、rounds=0、零 token。G1-G4 依旧全绿未拦截。定位：B0 driver 把 registry 原始 schema（{name,description,parameters}）直接作为 tools 发给 provider，而引擎实际发送前经 ToolCycleService._schema_to_param 转成 OpenAI wire 形态 {\"type\":\"function\",\"function\":{...}}；GLM 端点严格校验 → 400 \"tools[0].type: type cannot be empty\"。b1 行（引擎路径）不受影响，t4/t5 b1 真实完成。"
root_cause: ""
solution: "1) 判别行有效性先看 usage（rounds/tokens），provider_error+rounds=0 即 LLM 未被调用，属基础设施缺陷而非测量结果；2) 最小复现探针：同 payload 直调 engine.llm.chat 打出 provider 原始错误（避免只看终态分类）；3) 修复锚定同源：b0_driver 用 engine._tool_cycle._schema_to_param 逐 schema 转换（引擎同一方法对象），并加漂移断言（type/function.name 必在）；4) G2 假 client 断言同步适配 wire 形态并强化（assert all t.type==\"function\"）——资格门从\"工具面名字一致\"升级为\"线路形态一致\"；5) 行记录增 b0_tool_wire_sha256 溯源；6) 按冻结纪律重建完整性链（新 preflight 记录新代码 hash + gates 全绿）再放行，作废 run 整目录保留为事故记录，绝不续写混版本 rows.jsonl。"
evidence: "复现探针（raw payload → HTTP 400 tools[0].type cannot be empty；wire payload → SUCCESS content+1 tool_call, tin=1099）；引擎同源转换 .worktrees/compaction-merge-20260916/src/llm_loop/core/loop/engine_services/tool_cycle.py:654 _schema_to_param；引擎调用点 core/loop/engine.py:2057；修复后 G2/G3 假 client 干跑 ALL_OK=true（含新增 type=function 线路断言）；行记录证据 results/hev0-p3-20260921T012806Z/rows.jsonl t4::b0 provider_error rounds=0"
tags: [wire-format, tool-schema, same-source, gates-coverage-gap, provider-400, hev0, openai-compat]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-21T09:36:49.045708+08:00"
updated_at: "2026-09-21T09:36:49.045708+08:00"
supersedes: [EXPERIENCE-20260817-llm, EXPERIENCE-20260921-client-http-header-env-api-key]
---

G1 的"逐字节一致"比较停留在 raw schema 层（registry 输出对 registry 输出），而 provider 线路格式是引擎运行时另一层转换（_schema_to_param）。"同一对象"的同源断言必须锚定到 wire 序列化的同一转换函数，否则存在 registry→wire 的未覆盖缝隙。另一教训：provider_error 终态行 reward=0.0 会被机械地记录为"可判分"，但 LLM 零调用的行不是测量行——判"全部可判分"前必须核 usage（rounds>0 / tokens>0），纯终态字段不足以证明行有效。