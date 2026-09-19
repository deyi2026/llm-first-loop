# Fleet 最小纵切 live qualification（真实 LLM spawn + 跨进程 reclaim）

- 日期：2026-09-19
- 候选基线：main @ `5fb75d897`（PR #34 + #35 合入后）
- Harness：`scripts/qualification/fleet_live_spawn_reclaim.py`（隔离状态目录，不触碰共享 runtime 与生产 data 目录）
- Provider：glm-5.3（`data/providers.json` glm 条目 + `GLM_API_KEY`，openai-compat 直连）
- 复现：`set -a && source .env && set +a && .venv/bin/python scripts/qualification/fleet_live_spawn_reclaim.py --phase spawn --root /tmp/fleet-live-qual-4`，随后新进程 `--phase recover` 同 root。

## 结论

**PASS（最终轮 run-4）：spawn 13/13 + recover 5/5，双进程、真实 LLM、隔离盘上状态。**

Project/ExecutionWorkspace/WorkerLease/reclaim 最小纵切在真实 spawn 路径上的机械事实全部成立：

1. 真实子代理经 `SubAgentRunner`（注入 `ProjectCoordinator`）spawn，~5s 内 terminal（outcome=`ok`），final_answer 为真实模型实质回复。
2. 盘上 lease `lease-ws-1-g1` 终态 `settled`，settlement 携带 `parent_session_id` 归属。
3. `fleet/state.json` workspaces registry 记录 `ws-1`（physical_root 指向 per-run 目录；物理目录按设计惰性物化，本次无文件写入故未创建——这是 registry-first 设计，不是缺口）。
4. facts 流（`fleet/facts/ws-1.jsonl`）含 `run_started`/`run_settled`，均带 parent 绑定；`facts_summary`（G2）盘上可得。
5. 跨进程（新进程重建 store/coordinator/runner）：`parent_of` 从盘恢复正确；`topology_lease_view`（G3）返回 settled lease + facts_summary。
6. 崩溃 lease（TTL 3s，不 settle 即"死"）：过期后 `reclaim_run_if_expired` 代际 1→2；用旧代句柄写 fact 被 `FencedError` 拒绝（"stale worker rejected: lease lease-ws-2-g1 is not the current active generation of ws-2"）；回收后新代 lease 正常 settle。

## 诊断过程（保留失败记录，防止结论被误读为一次通过）

- run-1：真实 LLM 调用 >120s 未返回（provider 侧悬挂，直连探针 2.9s 正常），进程退出后 session 停在 active——本身即真实 crash 场景素材。
- run-2：子代理 ~5s 正常完成，但 harness 把 outcome 词表写错（真实值为 `ok`，非 `success`），结果字段应为 `final_answer`。修正后 12/13。
- run-3：唯一 FAIL 是 harness 无法从 `recover()` 构造旧代句柄（recover 返回的是新代）。修正为 spawn 阶段把 crash lease 完整字段存入 spawn_meta，recover 阶段重建 `WorkerLease` 旧代句柄直接写。
- run-4：全绿。

## 观察记录（不裁断）

glm-5.3 连续两轮拒绝"仅回复指定令牌"式指令，理由是无法核实父代理授权链（真实模型行为）。live qualification 的判定标准因此取"实质回复 ≥10 字符"而非令牌照抄；机制层 18 项检查不受影响。子代理授权语义如何向真实模型声明，属于后续产品层问题。

## 门禁

- `ruff check scripts/qualification/fleet_live_spawn_reclaim.py`：PASS
- 本地 A.5 manifest 覆盖：PASS（随本 PR）
