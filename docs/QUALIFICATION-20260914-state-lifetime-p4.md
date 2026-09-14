# P4 State Lifetime / Memory Plateau Qualification

日期：2026-09-14
分支：`fix/active-run-ingress-1214-20260914`
阶段：State Ownership / Context Integrity Plan — P4
原则：只治理机械 ownership / lifetime / retention；不引入 prompt 规则、任务语义判断或 completion 策略。

## 1. 裁决

P4 的目标不是“运行结束后清空一切”，而是把状态分成两类：

1. **durable truth**：Session/Event/Evidence/ExternalExecution/Provider settlement 等历史事实允许随历史增长，必须可恢复；
2. **process-local reconstructible state**：缓存、锁、活动句柄、订阅、运行提示只能跟固定活跃窗口增长，不能形成 all-session/all-run 强引用索引。

本阶段只对已证明会线性增长的第二类状态增加 bounded LRU、weak retention 或 terminal retirement。正在运行的 run/job/child 永不因容量压力被伪终止或静默淘汰。

## 2. State Lifetime Matrix

| State surface | Owner / lifetime | Durable SoT | Retirement | Recovery / safety invariant |
|---|---|---|---|---|
| `RunStateManager._buckets` | engine；recent cross-turn runtime hints | Session/Event 等 durable facts，不以 bucket 为 SoT | active pin + bounded idle LRU（默认 128） | active session 不淘汰；idle 淘汰后按后续 run 重新建立机械运行态 |
| engine per-session cache hints | engine；随 recent RunState window | 否 | RunState idle eviction 时 retire | 只清 `_cache_last_model_by_session` / 1210 attempt hint / request-count hint / cache monitor+guard 分桶，不删 Session/Event |
| `SessionStore._identity_verified` | SessionStore；验证加速 | `.identity/<sid>.json` | bounded LRU（默认 512） | 淘汰后重新读取 durable owner/tombstone；不会重新 claim |
| module SessionMeta cache | process；list/search 加速 | Session JSON | bounded LRU（默认 512）+ 文件变化/删除失效 | 淘汰后重新解析 JSON |
| EventStore parsed read cache | EventStore；hot reads | Event JSONL/segments | 既有 max 2 | last-seq/file identity 不匹配时重建 |
| EventStore cold-read build locks | EventStore；单次并发 cold read | 否 | weak-value table | 活跃 reader 持强引用；read 结束即可 GC |
| EventStore rotate throttle timestamps | EventStore；30s 性能提示 | 否 | bounded LRU（默认 512） | 淘汰只会多做一次安全 rotate check |
| Session/Event non-POSIX fallback locks/gates | process；持锁/等待期间 | 否 | weak-value table | 活跃 context 持强引用；无 owner/waiter 后可释放 |
| FileService process path locks | process；单次 path coordination | 否 | weak-value table | 活跃文件操作持强引用；路径操作结束后可 GC，不形成 all-path 索引 |
| WorkspaceStore process data-root locks | process；Store/registry coordination | Workspace registry JSON | weak-value table | 活跃 Store/operation 持强引用；Store 生命周期结束后 data-root lock 可 GC |
| prompt axis diagnostic previous-fingerprint cache | process；cache-axis observability | 否 | guarded bounded LRU（默认 512） | 淘汰只失去旧 session 的归因基线；不改变 prompt/provider-visible bytes |
| DeclarationValidator recent receipt hints | validator；近 N 轮 advisory evidence hints | Session/tool durable history | guarded bounded session LRU（默认 128）+ RunState retirement | 淘汰后只失去跨轮提示加速；声明匹配规则与 durable tool facts 不变 |
| MemoryExtractor cooldown timestamps | extractor；仍处于既有 cooldown 窗口的触发提示 | 否 | 按既有 `cooldown_s` 机械过期退休 | 只删除已经不可能再影响 trigger 判定的时间戳；提取内容/模型调用/触发阈值均不变 |
| `JobRegistry` local process handles | process；active + recent terminal | ExternalExecution/EventStore | active 永不淘汰；terminal recent cache（默认 128） | terminal handle 淘汰后 `snapshot` 从 durable journal 恢复；cancel 但未 `wait()` 收口的进程仍保留 |
| Provider settlement runtime cache | process；recent logical calls | EventStore append-only provider facts | bounded exact-call cache（默认 128） | exact `call_id` read-through；淘汰不制造第二个 CALL_OPENED |
| SubAgent durable topology cache | SubAgentRunner；recent child topology | child Session `parent_id` + topology Event | lazy bounded cache（默认 128） | exact child read-through，且 Session parent 与 Event edge 必须一致，否则 fail closed |
| BrowserPerception session identity/version state | adapter；active + recent Browser sessions | current-runtime integrity-protected session-state sidecar + immutable snapshots | per-session `RLock` + active pin + bounded inactive LRU（默认 128） | active state 永不淘汰；同 session writer 串行；eviction 后 exact generation/stable semantic identity read-through；runtime generation/nonce/integrity/expiry 不匹配均 fail closed |
| BackgroundRunner registry / worker ids | process；active run | run/session/event durable facts | worker terminal 时移除；EventBus replay close | stop timeout 若线程仍活着必须保留 handle，不能“删除即假装停止” |
| EventBus subscribers / replay spool | one active run/client transport | 否 | unsubscribe + bus close | 完成/取消/断连后无 subscriber；spool closed |
| run save capability / `_run_sessions` | exactly one active run | 否 | run finally / GeneratorExit | lease/save token/session strong ref 均释放；durable Session 已保存 |

## 3. 100 → 1K → 10K Plateau Gate

同一进程对 10,000 个机械 session/run identity 依次完成 activate/release、EventStore cold read、rotate hint、terminal background job、identity cache touch、SubAgent topology cache touch；每个检查点先 `gc.collect()`。

| count | RunState buckets | Event cache | cold-read locks | rotate cache | terminal jobs | identity cache | topology cache | threads | tracemalloc current | RSS (KiB, diagnostic) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 32 | 2 | 0 | 32 | 32 | 32 | 32 | 1 | 110,795 B | 85,920 |
| 1,000 | 32 | 2 | 0 | 32 | 32 | 32 | 32 | 1 | 3,958,081 B | 89,696 |
| 10,000 | 32 | 2 | 0 | 32 | 32 | 32 | 32 | 1 | 3,958,944 B | 89,712 |

关键结果：达到容量后，1K → 10K 额外 9,000 个 identity 只让 `tracemalloc current` 增加 **863 B**；所有被纳入 gate 的强引用容器完全不再增长。RSS 只作平台/allocator 诊断，不作为正确性硬阈值。

另做真实 durable Session 文件压力：实际创建并落盘 10,000 个 Session/identity facts，在 100/1K/10K 检查点执行 `list_sessions()` + GC。磁盘 Session 数按历史增长到 10K，identity verified 与 SessionMeta RAM cache 均保持 qualification window `<=32`。这验证了“durable history 可增长，但 RAM 不得靠强引用复制历史”的边界。

## 4. Lifecycle / Recovery Gates

- GeneratorExit：释放 run lease、`_run_sessions` strong ref、RunState active pin；Session continuity 仍可恢复。
- BackgroundRunner stop/cancel：正常终态移除 registry/worker；stop timeout 对仍运行线程返回 `shutdown_timeout` 并保留 handle，直到真实 worker 终态。
- SubAgent finish/restart：active handle/mailbox 清理；历史 topology 按 child id 从 Session+Event read-through 恢复。
- JobRegistry terminal eviction：本地 Popen/output handle 可淘汰；durable exit code/state 仍可从 ExternalExecution journal 查询。
- EventStore delete：立即失效 hot parsed cache 与 rotate hint；后续读取只得到真实空事实。
- Provider settlement eviction：淘汰后 exact call rehydrate；不重复创建 logical provider call。
- Session archive/delete/resource fence、fork/disconnect、orphan tool cancellation 与 interrupted-run continuity 均保持原机械语义。

## 5. Qualification Results

- P4 lifecycle release 扩大矩阵：**148/148 PASS**。
- P4 + continuity/recovery 相邻矩阵：**185/185 PASS**。
- Provider settlement / resource projection / rotate wiring / external execution / BackgroundRunner：**83/83 PASS**。
- 100→1K→10K ephemeral plateau：**PASS**。
- 10K real durable Session growth vs RAM-cache plateau：**PASS**。
- Ruff：PASS。
- `py_compile`：PASS。
- Pyright：**0 errors / 0 warnings / 0 informations**。
- `git diff --check`：PASS。

现有 pytest side-effect audit warning 与 Starlette/httpx deprecation warning 为既有非阻断诊断；本阶段未通过隐藏 warning 取得 PASS。

## 6. 明确未做

- 未 blanket-clear Session/Event/Evidence durable state。
- 未对 active run/job/child 做容量淘汰。
- 未用 deep-copy 把 ownership 问题转成额外内存开销。
- 未加入 prompt、模型行为规范、任务相关性或 completion 判断。
- 未进入 P5 provider-visible Context Integrity，也未删除 P6 legacy fallbacks。
- 未 push、未重启、未部署、未启动第二个本地模型。
