---
title: 本地模型工具参数完整度提升：P0 声明一致性 + P1 precheck 兜底 + P2 schema 描述强化
scenario: 本地模型（qwen3.8-27b）工具调用参数完整度偏低（58%），需定位根因并提升：区分检查器假阳性与模型真实漏参，程序层兜底（precheck required 校验）与提示层强化（schema description）分层实施。
root_cause: 本地模型参数完整度 58% 中混两类缺失：①检查器与 schema 声明不一致的假阳性（send_email schedule 可选却按必填判）；②模型真实漏参（translate_text 漏 target_lang、get_weather 部分漏 city）——多参数工具省略非首参数。
solution: "P0 修一致性: 检查器从工具 schema required 动态校验（声明=检查），消除假阳性；send_email 若业务必填则提 schedule 入 required。P1 程序层兜底: 生产 precheck 已装配（factory.py:759）且 required 缺失校验已存在（precheck.py:156 'required but missing'），开关 precheck_enabled 动态可控（runtime_params 白名单 0/1）——缺参返回引导反馈让模型补传。P2 提示层: 多参工具 description 声明必填清单 + 参数加 description/示例（target_lang 如 en/zh/ja）。P3 结构: 嵌套对象（schedule.date/time）拆平为顶层参数或拆两次调用。P4 few-shot: 系统提示注入一条正确多参调用示例（本地模型模仿>理解）。"
evidence: bench_local_toolcall_v2.py T4 全 0/4 miss=schedule.date/time；schema required 仅 to/subject/body（声明与检查矛盾）；T6 全 0/4 miss=target_lang（required 已声明仍漏）。P0 修改后 check 动态按 schema required 校验 + send_email schedule 提为必填 + 嵌套对象非空即存在；P2 给多参工具加参数 description。
tags: [参数完整性, 工具调用, 本地模型, schema, precheck]
source: {}
status: active
created_at: "2026-08-22T21:44:40.094512+08:00"
updated_at: "2026-08-22T21:44:40.094512+08:00"
---