---
title: Learning Plane 零消费根因：RG-1 fallback 车道 × lfrt revalidate 结构性 fact_conflict（云 provider 部署）
scenario: "llm-first-loop 部署（纯云 provider，无本地 runtime fact）：Learning Plane 启用后 learning job 永不消费，journal 无界增长，新 job 全部饿死。适用于任何\"默认启用后功能零产出但无报错\"的资源调度类诊断。"
root_cause: ""
solution: 判定顺序：① 事件分布统计（admit/requeue/attempt/时间戳）区分瞬态争用 vs 确定性失败；② 沿 job 生命周期逐 raise 点对表部署事实（云 provider=NOT_APPLICABLE 是合法态）；③ 单独验证调度器的选取语义（max_n FIFO 槽位占用）。修复方向：无 LFRT 事实的进程内 fallback 车道不应进入 lfrt revalidate（构造性无事实≠冲突）；requeue 必须计 attempt+backoff 落 dead-letter，防永生与饿死。
evidence: "journal.jsonl 21:15:39 自旋现场；learning_plane.py:126-137/226-238；provider_calls.py:222-247；learning_journal.py:234-263；EVO-20260917-c8555e75 全文及代码行引用"
tags: [learning-plane, resource-admission, lfrt, deadlock-diagnosis, evo-c8555e75]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-17T21:24:12.318714+08:00"
updated_at: "2026-09-17T21:24:12.318714+08:00"
---

诊断路径（可复用）：
1. 事件分布统计（admit/requeue 计数、attempts、首末时间戳）先于源码阅读——712/712 全同 reason + attempts=0 + 跨两代部署与两次重启不变 ⇒ 立即排除瞬态争用，定位"确定性失败"；
2. 沿 job 生命周期读 admit→revalidate 全链，把每个 raise 点的触发条件与部署事实（云 provider / 无 providers 注册）对表；
3. runnable_jobs(max_n=5) 的 FIFO 语义要单独验证——"从未被调度"的 job 与"循环失败"的 job 是两个独立缺陷叠加；
4. 失败路径的副作用（revalidate 失败顺带 invalidate limit/generation）会把"瞬态冲突"伪装成"永远 mismatch"，读代码时先标出所有写侧副作用再下结论。

教训：默认启用上线前只验证了"配置面生效"（auto/on、入队正常），没有验证"消费面产出"（一个 job 走到终态）。启用类变更的验收必须包含至少一次端到端终态观察。