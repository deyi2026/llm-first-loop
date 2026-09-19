# Fleet 最小纵切设计（2026-09-19，基线 2939deea6）

## 范围：三种机械身份 + 一条真实 Gate

- `ProjectRecord`：稳定 `project_id` 与所拥有 execution workspace/worker 的机械关联。
- `ExecutionWorkspace`：workspace 身份、物理 root、repo/HEAD 等事实。
- `WorkerLease`：`project_id + workspace_id + worker_id + generation + owner_id` 的执行所有权。

程序只回答一个问题：**这个物理 worker 现在有没有权提交这个 generation 的副作用/结果？**
任务重要性、继续与否、完成与否、哪个结果更好——全部留给模型/协调者。

## 机制

- 磁盘是唯一权威（`state.json` 闭 schema `lfl.fleet.registry/v1` + 每操作 fcntl 跨进程锁 + 原子替换写）。
- 旧协调者的内存句柄对新代写入必然 fail-closed（`FencedError`）：每次写都重读盘上当前代。
- `reclaim` 是 CAS：标记旧代 superseded，签发新代。
- settlement 每 workspace 恰好一次（`SettlementError`）；facts 以 JSONL 追加且不可被过期代污染。
- liveness 判断不存在：何时 reclaim 是协调者/模型的决策，程序只提供 CAS 与 fencing。

## Gate（tests/unit/test_fleet_reclaim_gate.py，全绿）

P→W 创建；G1 取 lease；部分 durable facts；owner 消失（无释放）；新协调者从盘恢复；reclaim→G2；
G1 迟到写/迟到 result fail-closed；G2 继续；唯一 settlement；再重启证明同终态。

## 非目标

无调度、无能力路由、无结果质量裁决、无 liveness 探测、无跨机网络层。
本纵切基于冻结的 Fleet Prebaseline（2939deea6），独立 worktree/Goal/证据链。
