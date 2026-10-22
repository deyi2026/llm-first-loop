# RUNBOOK: archive-stale 批量归档（2026-10-21 v1）

## 一句话

`lfl archive-stale` 把超过 N 天（默认 **5 天**）未更新的 active 会话批量归档；
先 `--dry-run` 看候选，再真跑。归档只改 `status` 字段，可逆、不删数据。

## 背景

2026-10-20 手工批跑（1 条试点 + 全量 39 秒）验证了语义；本命令把那套一次性
脚本收编为产品能力，消除跨会话交接成本。本次将阈值从试点期的 3 天改为默认 5 天。

**默认策略（维护者确认 2026-10-22）**：Web 宿主内默认启用自动归档循环（首启延迟 60s、
周期 24h、阈值 5 天）经维护者明确确认保留，不做 opt-in 改造；确有隔离需求的环境用环境变量
关闭或调阈值（见下文变量表）。此前审查提出的"默认启用未见授权"以此为准关闭。

## 用法

```bash
lfl archive-stale --dry-run            # 只列候选（含 workspace/age/title），写报告
lfl archive-stale                      # 执行归档
lfl archive-stale --days 3             # 覆盖阈值
lfl archive-stale --data-dir ./data    # 指定数据目录（默认 ./data）
lfl archive-stale --report /tmp/r.jsonl
```

薄壳命令：不装配引擎、不需要 LLM 凭据。

## 口径（冻结）

| 维度 | 语义 |
|---|---|
| 锚点 | 命令启动时刻（system_local_now） |
| 过期判定 | `updated_at` **严格早于** 锚点 − N 天；恰好等于不算 |
| 范围 | 工作区注册表全部未退休工作区分区（`data/sessions/<ws-key>`）；注册表为空时回退平铺 `data/sessions` |
| 候选过滤 | `status == "active"` 且未 `pinned`；最老优先 |
| busy | 会话运行中（run_lease 被占）→ 跳过并记录，退出码仍为 0 |
| 身份冲突 | owner 记录不属于当前分区（`.identity/<sid>.json` 不匹配）→ 跳过并记录 |
| 并发消失 | archive 返回 False → 记录 missing，继续 |
| 指针 | 归档成功后若该工作区 `shared_current` 指针指向此会话 → 清空（防跨端解析到归档态） |
| 幂等 | 已归档会话 status 非 active，重跑不重复命中；中断可直接重跑 |

## 归档副作用（与单条 `lfl archive <sid>` 完全一致）

1. `status: active → archived`（JSON 原地改写，消息与事件不动）
2. `updated_at` 刷新为归档时刻
3. 追加一条 `session.meta_changed` 事件（归档动作本身可追溯）
4. **不可逆点**：归档后 `updated_at` 变新，若再想按时间找它需按 `status=archived` 过滤

## 恢复（unarchive）

把会话 JSON 的 `status` 改回 `"active"`（或用 Web UI 归档视图恢复，如可用）。
数据从未被移动或删除。

## 报告与退出码

- 报告：`data/reports/archive_stale/<YYYYMMDD-HHMMSS>.jsonl`，每行一条处置记录
  `{workspace, session_id, title, updated_at, age_days, action, error}`；
  `action ∈ {dry-run, archived, busy, identity_conflict, missing, error}`
- 退出码：`0` 无处理错误（含 0 候选与 busy/冲突跳过）；`1` 存在处理错误；
  `2` 参数/致命错误（如注册表损坏）

## 已知边界

- 退休（retired）工作区分区不处理——其会话本就不在活跃列表
- 跨数据目录搬迁遗留的孤儿文件（owner 记录缺失/外区）会持续报 identity_conflict，
  属预期保护，不自动认领
- 同一秒内多次运行会覆盖同名报告文件（时间戳精度为秒）

## 验证

- 单测：`tests/unit/test_cli_archive_stale.py`（边界/pinned/busy/冲突/指针/幂等/多分区/--days）
- 循环单测：`tests/unit/test_archive_stale_loop.py`（到期判定/禁用开关/端到端线程/错误态自愈）
- 2026-10-21 冒烟：临时数据目录 dry-run → 真跑（归档+指针清理）→ 幂等重跑，全部通过

## 自动模式（web 服务常驻，2026-10-21 v2）

手动命令保持不变；web 服务进程内另有 `ArchiveStaleLoop` daemon 线程
（`src/llm_loop/workspace/archive_stale.py`）按周期自动**真跑**同一核心例程：

- 宿主 = web 服务（`python -m llm_loop.web`）——本安装常驻进程，零新增守护/定时器
- 节奏：启动 60s 后首轮检查，此后每 5 分钟（TICK）检查是否到期；到期即跑一轮，默认周期 24h
- 状态：`data/reports/archive_stale/auto_state.json`（last_run / next_due / days / 轮次摘要）；
  **服务重启不重复跑**——到期判定基于持久状态而非内存计时
- 环境变量（web 进程读取；非法值回退默认并告警，不影响启动）：

| 变量 | 默认 | 含义 |
|---|---|---|
| `LFL_ARCHIVE_STALE_AUTO` | `1` | `0` 总关闭 |
| `LFL_ARCHIVE_STALE_DAYS` | `5` | 过期阈值（天） |
| `LFL_ARCHIVE_STALE_TICK_S` | `300` | 到期检查间隔（秒） |
| `LFL_ARCHIVE_STALE_PERIOD_S` | `86400` | 两轮自动归档最小间隔（秒） |

- 判定语义、busy/身份冲突跳过、shared_current 指针清理、jsonl 报告与手动命令完全一致（同一实现）
- 异常自愈：单轮失败只记入状态文件 `summary.error` 并顺延一个周期，不影响 web 服务；
  pytest 环境自动禁用（PYTEST_CURRENT_TEST 守卫）
- 排查：`cat data/reports/archive_stale/auto_state.json`；每轮摘要日志走 web 服务
  `llm_loop` 命名空间 INFO（`archive-stale auto: ...`）
