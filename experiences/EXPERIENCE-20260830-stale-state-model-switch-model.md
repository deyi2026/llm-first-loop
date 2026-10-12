---
title: 装配漂移根因：前端 stale state.model 每轮写回覆盖 switch_model（回执成功但路由未变）
scenario: "任何\"工具/命令回执成功但实际效果未生效\"的 bug 排查，尤其涉及：①工具修改会话状态 ②web 前端持有状态副本 ③前端每轮请求重发状态（payload.model 等）→ 后端写回覆盖工具写入。本例：llm-first-loop web 端 switch_model 切换成功但下一轮 model_aware_budget 仍显示旧模型。"
root_cause: "web 前端 state.model 无运行时同步通道（仅页面加载时读一次），而 app-core.js:51 每轮 chat 请求都携带 state.model；后端 routes.py:303-306 _apply_session_model_override 对 payload.model 无条件写回 sess.model_override。run 内 switch_model 工具切换成功写入后，下一轮请求携带的 stale payload.model 将其静默覆盖——形成\"切换回执成功但路由回旧模型\"的装配漂移。"
solution: "①取证分流：grep 写入路径（events.py:_set_session_override）与读路径（routing.py:173）分别验证均健康 → 锁定第三写入口（web 层 _apply_session_model_override 无条件写回）。②根治选回填闭环：前端在 done 事件消费点（stream-chat.js buildAssistantNote，覆盖全部 4 个调用点）用 data.model_used（engine 每轮 LLM 调用刷新，反映 run 内切换后最终模型）回填 state.model + modelSelect UI → 下一轮请求携新值 → 写回 no-op，零窗口闭合。node --check 通过，刷新页面即生效。③防御层提交演进：routes.py 写回覆盖时 logger.warning（可观测兜底），EVO-20260829-ad8c5984 待人工审阅。④长期方案（未实施）：LWW 时间戳仲裁（sess.model_override_ts），涉及 Session 持久化格式变更需单列演进。"
evidence: "EVO-20260829-ad8c5984（含完整根因链与修复 diff）；action_trace 2026-08-29 会话 68fed5f5/996e7e52 复现实证；代码取证：app-core.js:51、routes.py:210-213/303-306、events.py:281、routing.py:173-181、engine.py:384/507、command-upload-model.js:203-204；修复落地 stream-chat.js（edit_file 校验 + node --check 通过）"
tags: [last-writer-wins, switch_model, 装配漂移, web-frontend-stale-state, 回执与实际不符, 根因分析, model_override]
source:
  session_id: 996e7e52-82c3-4fc5-82ea-fff5863c2969
  evolution_id: EVO-20260829-ad8c5984
  fix_file: src/llm_loop/web/static/modules/stream-chat.js
status: active
created_at: "2026-08-30T02:14:29.513449+08:00"
updated_at: "2026-08-30T02:14:29.513449+08:00"
---

## 排查路径（10 步定位，全程代码取证）

1. 现象与回执矛盾：switch_model 回执"[状态: 成功]"，但 action_trace 中 model_aware_budget 持续显示旧模型 → 判定"写入路径或读路径之一断裂，或写入后被覆盖"
2. grep 定位写入路径：tools_model.run_switch_model → events._set_session_override → sess.model_override = value（健康）+ loop 末自动持久化
3. grep 定位读路径：routing.py:173 每轮 tool loop 重新解析 sess.model_override 路由 client（健康）
4. 双路径都健康 → 锁定"第三写入口"：grep model_override 全量 → 发现 web/routes.py 的 _apply_session_model_override
5. 关键发现：routes.py:210-213 每轮 chat 请求把 payload.model 规范化后作为 on_run_acquired 回调；303-306 行 if model_ref != override: 无条件写回
6. 时序推演：run N 中工具切换（写 override=新）→ run N 结束 → run N+1 请求携 stale payload.model → 写回覆盖回旧值 → 漂移
7. 前端取证：app-core.js:51 if (state.model) body.model = state.model（每轮必带）；command-upload-model.js:203 state.model 仅页面加载时同步一次 → stale 源头确认
8. 回填钩子取证：engine.py:384 model_used 每轮 LLM 调用刷新（反映 run 内切换后的最终模型）→ done 事件已传前端（buildAssistantNote 已读但仅用于页脚）
9. 修复：前端在 done 消费点回填 state.model + 选择器 UI（复用已有 option 匹配先例）→ 下一轮请求携新值 → 写回 no-op → 零窗口闭合
10. 防御层：后端写回覆盖时 logger.warning（可观测兜底），提交演进建议人工审阅

## 通用方法论

- "回执成功但实际未生效"→ 先分别验证写入路径与读路径，都健康则找**第三写入口**（本例：web 层 per-request 写回）
- web 前后端各有状态副本时，任何"每轮请求都重发状态"的设计都会形成"最后写入者赢"竞态，工具侧修改必被覆盖
- 修复优先选**回填闭环**（利用已有 done.model_used 反映最终事实）而非加仲裁时间戳（涉及持久化格式变更，侵入大）