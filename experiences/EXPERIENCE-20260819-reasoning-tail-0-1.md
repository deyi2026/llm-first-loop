---
title: 缓存命中下降根因：REASONING_TAIL=0 思考链全保留稀释命中率，修复=-1 模式按属性省略（已验证最短路径）
scenario: "会话中窗口缓存命中率持续缓慢下降（98.78%→97.19%），单轮命中率 87-95%，输入 tokens 每轮暴涨（思考链占比 22%→51.7%）。需要区分\"断点\"与\"稀释\"两类低命中并定向修复。"
root_cause: "REASONING_TAIL=0 将思考链（每轮不同的大动态块）全量保留并提交，输入体积持续膨胀，新增内容必然 miss，稀释窗口命中率——不是前缀断裂。旧\"最近 N 轮\"裁剪（>0）则相反：按轮次滚动省略导致同一消息 reasoning 从有到无，每轮改前缀制造真断点。两种参数各有缺陷，-1 模式按属性省略两者兼治。"
solution: 1) 归因：断点类（gate_drift/锚点/压缩事件）全部排除后，看 guarded_requests.jsonl 每轮真实 in/hit——增量命中率 >100%（回补）说明前缀缓存正常，miss 绝对值大 = 新增内容多。2) 根因：REASONING_TAIL=0（全保留思考链）使每轮提交视图新增 5-10K tokens 思考链（首次出现必 miss）→ 单轮 miss 占比升高 → 窗口累计被稀释下降。3) 修复：history.py _apply_reasoning_tail 新增 -1 模式——仅保留携带 tool_calls 的 assistant 思考链（M20 协议必需），其余省略；按属性（是否带 tool_calls）而非按轮次滚动省略 → 前缀字节稳定 + 输入最小化。4) 验证：.env REASONING_TAIL=-1 + 重启 web/feishu，实测输入 164K→139K（-15%），切换期单轮断点 9.2% 为预期内一次性事件（提交视图形态变化），第 2 轮恢复 92%，长期回归 99%。
evidence: "guarded_requests.jsonl 会话 a49c055c：重启前 09:08-09:10 单轮命中率 87-95%、增量回补 137-352%；重启后 REASONING_TAIL=-1 生效：in 150244→139359（-15%）、断点轮 9.2% 后第 2 轮 92.0%。git commit 998fdf2。用户批准方案 A（2026-08-19）。"
tags: [缓存命中, 前缀缓存, REASONING_TAIL, 思考链, tool_calls, history.py]
source: {}
status: active
created_at: "2026-08-19T17:32:05.870436+08:00"
updated_at: "2026-08-19T17:32:05.870436+08:00"
---

完整链路：诊断（event_stream 排除断点事件 + guarded_requests 增量命中率回补判定）→ 根因（REASONING_TAIL=0 思考链全保留稀释）→ 修复（history.py -1 模式：仅保留携带 tool_calls 的 assistant 思考链，M20 THK-04 协议必需；旧语义 0/2 零改动保证可回滚）→ 参数（.env REASONING_TAIL=-1）→ 重启（web/feishu 优雅重启加载新代码）→ 验证（输入 -15%、断点后第 2 轮恢复 92%）。回滚预案：参数改回 0 或 git checkout history.py。