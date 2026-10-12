# AUDIT-20261008 · durability observe surfaces 只读审计

- 日期: 2026-10-08 07:31–07:36 (session: 服务 gen196 稳态期, git 29a77e07c)
- 性质: **只读审计**。未改任何生产代码/注册表/状态文件；产物为本报告 + `tmp/audit_durability*.py`（分析脚本）。
- 范围: `tests/guards/function_size_baseline.json :: durability_registry` 全部 84 面中 status=observe 的 77 面（T2×43 / T1×32 / T3×2），对照 `docs/DESIGN-20261007-durable-run-contract.md` tier 红线。
- 方法: 两级 AST 扫描（文件级信号 → 函数级调用点归因）+ 人工抽查 14 处写点原文。锁文件 open（flock 用途、不承载 payload）按 learning_runtime.py 豁免先例排除。

## 结论摘要

| 分级 | 含义 | 数量（T2 observe 内） |
|---|---|---|
| R1 非原子覆写 | ScheduleStore 事故同类（裸 write_text 覆写承载状态文件） | **12 处写点 / 9 个面** |
| R2 fail-open 吞写失败 | 原子性有/无，但写失败被静默吞掉 | 2 个面 |
| R3 应重分类 conform | 写路径已达 conform 级（tmp+replace+fsync），仅注册表未刷新 | 4 个面 |
| R4 tier 错登 | 登记 T2 实为 append-jsonl（T1 语义） | 2 个面 |
| R5 结构性 | 原子写助手 7+ 处局部实现，无共享 util | — |

T1 32 面中：9 机械判定 APPEND-OK；MIXED 5 中 2 处真覆写（见下）；18 处 NO-WRITE-FOUND（经 helper/append handle 写入，未深核，列入下轮）。T3 2 面未深核。

## R1 非原子覆写（按业务影响排序）

| # | surface | 写点 | 影响 |
|---|---|---|---|
| 1 | **backup_store** | recovery/backup.py:122 `save_archive`, :169 `mark_recovered` | **恢复路径自身**。备份/恢复标记半写 = 主文件出事时备份同时不可用 |
| 2 | **method_store** | tools_method.py:569,573 `_ensure_runtime_copy`, :888 `update_status`, :1004 `annotate_freshness` | method 状态翻转（qualify/activate）覆写撕裂，跨会话方法状态错乱 |
| 3 | **archive_store** | memory/archive.py:452 `rebuild_segment_index` 覆写, :834 `update_summary`, :939 cleanup | 索引重建覆写半态 → search_archive 检索失效 |
| 4 | **evolution_store** | introspection/evolution.py:324 `_transition` | 有 flock（好）但 write_text 非原子；exec_override 授权流转丢失风险 |
| 5 | interop_mailbox | core/loop/engine_services/interop.py:228 归档 | best-effort 归档，源消息保留 pending（不丢数据）→ 中低 |
| 6 | smx_snapshot_store | core/loop/smx.py:498 | 快照覆写 |
| 7 | err1210_snapshots | core/loop/err1210.py:79 | 诊断快照，低危 |
| 8 | dsh_plugin_cache | introspection/tools_skill_dsh.py:87 | 纯缓存可重建（建议按缓存语义豁免/降级而非迁移） |
| 9 | task_quality_cache | task_quality/dep_graph.py:256 | 同上 |
| — | handoff_store | tools_handoff.py:187 | fresh-dir write-once（写新目录不覆写旧态）→ 降为低危观察 |
| — | job_registry(通知) | tools/builtin/job_registry.py:486 | 观测性 payload best-effort → 可接受 |

排除项（曾疑似、人工核后排除）: session_store:1691/:1854 为 corrupt-backup/trim-archive 的**副本**写（live 文件走 `_durable_replace_text` 原子路径）；attachments.py:148/157 为 fresh-dir write-once（目录先建、元数据后经 `_atomic_write_json` 提交）。

## R2 fail-open 吞写失败

- feishu/feishu.py session_map `_save`（feishu_session_map）: tmp+replace 原子 OK，但 `except OSError: pass` 静默——建议至少 log。
- memory/store.py `_save`: 原子写失败回退**裸 write_text**（fail-open 降级同时引入 R1 非原子窗口）。

## R3 建议重分类为 conform（注册表刷新，属变更，待授权）

- **goal_store**: introspection/goal.py `_atomic_rewrite` = tmp+fsync+replace+dir-fsync。
- **episode_store**: memory/episode.py 追加 `open("ab")`+单行+fsync；截断工件内容寻址 + 全 fsync 链。
- **browser_perception_store**: browser/perception.py persist = tmp+replace + sha256 完整性字段 + 读侧 fail-closed。
- **session_store**: live 路径 `_durable_replace_text` 原子（备份裸写属副本，不影响主态）。

## R4 tier 错登（登记修正，属变更，待授权）

- extractor_state（memory/extractor.py:395 `open("a")` 单行）、learning_idle_state（runtime/learning_idle.py:47 `open("a+")`）: 实为 append-jsonl（T1 语义），当前登记 T2。

## R5 结构性发现

局部原子写助手 7+ 处：`memory/attachments.py _atomic_write_json`、`runtime/cognitive/state.py _atomic_write_text/json/bytes`、`core/session.py _durable_replace_text`、`introspection/goal.py _atomic_rewrite`、`browser/perception.py` 手写 tmp+replace、`memory/store.py` 手写 tmp+replace、`feishu/session_map.py` 手写 tmp+replace。**无共享 util**；下一迁移（experience_store, 已标 migrate）将手写第 8 份。建议提交 EVO：收敛到 `llm_loop/common/durable_io.py`（atomic_write_text/bytes/json + 可选 fsync/dir-fsync + 显式 fail 策略参数），旧助手逐批切换。

## 建议迁移顺序（修订设计文档 §6）

1. **backup_store**（R1#1，恢复路径自身）
2. **method_store**（R1#2，状态翻转）
3. **archive_store**（R1#3，检索失效）
4. evolution_store（R1#4，有锁缺原子）
5. experience_store（设计文档原定 #7，已标 migrate）
6. 其余 R1#5–9 按 low-risk 顺序或按缓存语义豁免

## 未尽事项（下轮）

- T1 18 个 NO-WRITE-FOUND 面深核；T3 2 面深核。
- semantic_state / synopsis_records / evidence_ledger / feishu_compensation / honesty_feedback（T2 NO-DIRECT-WRITE，写点经间接层）逐个确认。
- 状态面 cross-process 写纪律（单写者假设）审计：本报告只核写入原语，未核并发纪律。

## 证据

- 扫描器: `tmp/audit_durability.py`（文件级）、`tmp/audit_durability2.py`（函数级）、结果 `tmp/audit_durability_result.json`
- 抽查原文: backup.py:118-128, archive.py:448-458, evolution.py:318-330, goal.py:315-340, episode.py:280-325/438-456, perception.py:550-640, session_map.py:150-175, store.py:225-295, session.py:1685-1700/1848-1862, interop.py:222-235, job_registry.py:480-492, dep_graph.py:250-262, tools_handoff.py:182-192, attachments.py:140-165
