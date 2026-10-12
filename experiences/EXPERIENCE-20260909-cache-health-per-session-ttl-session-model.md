---
title: "cache_health 模型桶从账本升级为账本+契约：per-session 切换游标、切回热 TTL、(session,model) 前缀骨架契约"
scenario: "llm-first-loop 多会话并发 + 频繁模型切换（minimax/deepseek 双 provider），上下文缓存命中率监控需要区分\"模型无前缀 KV\"与\"会话流量问题\"，且要诚实评估切回旧模型时的 KV 驻留状态"
root_cause: ""
solution: "桶从\"账本\"升级为\"账本+契约\"：per-session 切换游标替代进程级；桶记录 last_active_ts，切回热判定加 2h TTL，过期降级为\"可能已过期\"；新增 (session, model)→skeleton_fp 前缀契约，postcheck 时校验骨架连续性，漂移仅审计计数+warning（fail-open 不干预不进 prompt）。全部 fail-open。"
evidence: "tests/unit/test_cache_health_buckets.py（26 passed）；tests/unit -k \"cache or guard or engine\" 434 passed 4 skipped；实现见 src/llm_loop/core/cache_health.py（_SWITCH_BACK_TTL_S=7200, _last_model_by_session, _model_prefix_contract, _contract_drift_count）"
tags: [cache-health, model-switch, kv-cache, prefix-contract, per-session, ttl, fail-open]
source: {}
status: active
created_at: "2026-09-09T23:42:01.772928+08:00"
updated_at: "2026-09-09T23:42:01.772928+08:00"
---

## 背景与问题
模型切换的 KV 命中观察中，cache_health 的模型桶只有计数（in/hit/runs）：
1. "切回热"判定无 TTL 依据——云端 KV 通常 5min~数小时过期，两小时后切回仍声称"仍热"是无据断言；
2. 桶不知道前缀内容——"切回时前缀是否还是切走时那份"无人校验，靠构建管线散落的约定；
3. record() 的 switched 判定用进程级 _last_model_ref 游标，交替并发会话每次 run 都误判切换。

## 修法（三层，fail-open，不进 prompt 文本）
1. **per-session 切换游标** `_last_model_by_session[sid]`：替代进程级判定；reset_session 清，reset(clear_buckets=False) 保留；
2. **切回热 TTL**（默认 7200s，构造可调）：桶新增 last_active_ts，仅当"桶有历史命中 AND 上次活跃在 TTL 内"才说"仍热"，超时降级为"桶仍热但距上次活跃 X 小时，云端 KV 可能已过期"；
3. **模型前缀契约** `_model_prefix_contract[sid][model_ref]=skeleton_fp`：postcheck 时校验 (session, model) 骨架连续性。切换不写 prompt 文本（R8.8），前缀头部跨模型共享，故切换不应改变骨架；骨架变=构建管线回归信号 → 仅 drift 计数+warning（fail-open）。skeleton 缺失沉默（宁缺勿滥）。

## 踩坑（本轮实测发现）
契约写入路径必须给会话 bucket 续命 `last_update_ts`：lazy cleanup 按 last_update_ts 判死会话（默认 0.0），只 postcheck 未 record 的会话会被判死并连同契约一起被 pop——契约刚建立就消失。单测用"先 snapshot(session_id)（per 分支不走 lazy cleanup）再 snapshot()（聚合走）"序列即可复现。

## 断言细节
- record() 中 _prev_active_ts 必须在 accum() **之前**取（accum 会刷新 last_active_ts），否则 TTL 永远不触发；
- 切回热的历史口径 = 桶计数减去本轮（hit - cached, runs - 1）。

## 测试
tests/unit/test_cache_health_buckets.py 新增 9 个：per-session 游标、TTL 过期降级、切换矩阵冒烟、契约稳定/漂移/silent/跨模型独立/跨切换存活、snapshot 审计暴露、reset 生命周期。26/26 过，关联面（cache/guard/engine）434 passed。