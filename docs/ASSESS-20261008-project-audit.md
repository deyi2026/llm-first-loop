# llm-first-loop 项目审查报告：缺陷复核与能力提升建议

- **审查日期**：2026-10-08（Asia/Shanghai）
- **版本**：rev4，本地修复核验与回归缺口追补版
- **原审查代码基线**：`500ee8f3eff02b12eacf77dede706e5d57a8d9c5`。本文默认的代码行号均绑定此提交，通过 `git show <SHA>:<path>` 核验。
- **本次复核方式**：直接读码、跨调用方核验、固定 release 上的模拟传输与隔离临时文件复现；未调用真实模型。
- **原报告来源**：LFL 主代理与 6 个隔离子代理的静态审查。本次没有重新运行该多代理流程，也没有重跑全量测试。
- **rev2 时点的本地更新**：main 当时为 `26c738076d3df7b42a760d3742bcbf03f6eb0eb2`，包含 CI 治理提交 `20be00979d72d6c0dea5f3fd2f19044ddf61efdb` 和 MethodStore T2 提交。这是历史快照，相关变化在 §3.8、§6 单独说明。
- **rev3 历史源码快照**：2026-10-08 17:10:57（Asia/Shanghai），main 为 `db378621e319c4dfb332a478c9fe25df59366800`；§0.3 保留当时的存续核验。
- **rev4 修复核验快照**：2026-10-08 18:42:32（Asia/Shanghai），main 为 `077eca97b30b21af8111385061fd90895e8316f8`；七提交的起始基线为 `1ef9652d922361ecea5a109201c95b1d712dd25c`，tracked 工作树干净。当前状态以 §0.4 为准；§1–§5 保留原基线的缺陷机制与验收要求，新修复锚点显式绑定 rev4 HEAD。
- **生效边界**：本地提交、release 代码与 live 服务是不同事实。本文没有重新做生产 currentness 验收，不能据本地 HEAD 推断已部署。
- **维护约束**：遵循 [开发与修复防退化手册](DEVELOPMENT_REPAIR_SAFETY.md)。本次只完善此报告，不修改行为代码、不提交、不发布、不重启、不推送。

## 0. 核心结论

**原基线存在可复现的异常传播、流式错误处理和状态计量缺陷；rev4 已核实七项本地修复提交与离线回归，但补充对照发现 BUG-13b、BUG-07 仍有缺口，不能接受“修复全部完成”的整体结论。** 原报告的“唯一 P0 死锁”“方法只剩 3 张可见”“测试门禁导致所有缺陷漏检”等结论仍不成立。

原可靠性顺序（流错误事实→锁异常传播→attempt 状态）已有本地实现。当前优先追补配置 mapping 来源回归和拨号观测过期两个可复现问题（§7.3），再完成最终候选及需要的集成/live 验收；已通过的窄范围修复不重复改造，不先扩大方法注入或调整模型参数。

Method 系统已经提供 candidate 检索、精确水合、使用回记、独立 qualification 与显式生命周期迁移。改进重点应是证明这些入口在真实任务中被正确发现、使用并带来收益；不能把 Learning 去重视图的窄过滤等同于整个方法库不可见，也不能把“缺少自动晋升”当成应当取消独立资格审查的理由。

### 0.1 证据与优先级口径

| 证据级别 | 含义 | 允许的结论 |
|---|---|---|
| R：离线复现 | 固定源码、明确输入、观察到异常或错误输出 | 已证实该输入下的机制；不证明生产发生频率 |
| S：静态确证 | 已读真实定义与调用路径，未做动态复现 | 存在代码契约缺口；影响规模仍需测量 |
| H：待验证 | 只有竞态窗口、残留字段或不完整引用 | 观察项，不计作已确证故障 |
| X：撤回 | 引用不符、因果不成立或混淆口径 | 不进入修复清单；保留勘误避免重复误诊 |
| L：本地已修复 | 在后续提交中看到对应实现与回归资产 | 不等于已发布或 live 验收通过 |

P0 指已证实的系统性阻塞、不可恢复的数据破坏或授权突破；**本轮没有足够证据确认 P0**。P1 指应优先修复的协议、异常传播或错误分类缺陷；P2 指受限场景的正确性、计量或可观测性问题。工程先后顺序还应考虑真实 provider 覆盖面、回归风险与已有工作，不用抽象“杠杆”压过可靠性。

### 0.2 原编号处置总表

编号保留以便追踪。BUG-13 拆分子项，避免把已复现问题和并发假设混为一项。

| 编号 | 原基线结论（当前状态见 §0.4） | 原证据 | 建议级别 |
|---|---|---|---|
| BUG-01 | 广域 `except OSError` 捕获锁内业务异常后二次 yield，替换原异常；原死锁归因撤回 | R | P1 |
| BUG-02 | 不同语义的 429 全被标为限流且允许 availability fallback | R | P1 |
| BUG-03 | SSE 业务码写入 HTTP `status_code` | R | P1 |
| BUG-04 | Anthropic/Google 流内 error 后返回部分文本，未标失败 | R | P1 |
| BUG-05 | 通用 JSONL 查询按物理顺序提前截断；不是 memory/method 专用检索的全局故障 | R | P2 |
| BUG-06 | 旧尺寸诊断注释与现行契约不一致，HEAD 自比较不能证明提交间不回退 | S | P2，治理核对 |
| BUG-07 | 已有配置优先级；有效路由状态未完整表达动态拨号地址 | S | P2 |
| BUG-08 | 原 release 的 MethodStore 写入耐久性缺口；后续 T2 已本地修复 | S / L | 上线状态待独立验收 |
| BUG-09 | 向量缓存部分写入未使用状态锁；业务影响与发生条件未复现 | H | 待验证 |
| BUG-10 | 所引行号是诊断字段，并无“首窗口截断”实现 | X | 撤回 |
| BUG-11 | Anthropic `message_delta.usage` 未更新最终输出用量 | R | P2 |
| BUG-12 | 无输出断连重试后 `truncated` 可残留 | R | P2 |
| BUG-13a/b/c | 非法布尔默认值、小数 timeout、带空格 # 的引号值解析问题 | R | P2 |
| BUG-13d | 全局 fallback notes 的并发隔离疑点 | H | 待验证 |
| BUG-14 | `retry_disconnect` 仅 OpenAI 路径使用；不是“三协议均失效” | S | P2，先明确 API 契约 |
| BUG-15 | reasoning-only 响应重试时已投递旧 attempt reasoning；重试展示与计量边界待完善 | R | P2 |
| BUG-16 | `max_retries` 未见读取；流时限按 attempt 创建，不等于已有 whole-call 时限被违反 | S / H | P2，契约核对 |
| BUG-17 | 原“28 处”未注明扫描范围；固定 release 复核为 src 30 / 全树 67 | R | 存量静态债 |
| BUG-18（新增） | 自定义目录排序能使 seed 覆盖 runtime，违背 runtime 优先意图 | R | P2 |

### 0.3 rev3 存续快照（历史记录）

用户提供的 LFL 独立复核指出 main 已前移，且 BUG-01/18 仍在。rev3 随后直接核对上述完整 HEAD 与工作树，并在隔离 namespace/临时目录中运行当前提交的真实函数，得到：

| 范围 | rev3 源码核验 | 当时动态核验与状态 |
|---|---|---|
| BUG-01 | `_shared_file_lock` 仍在 session.py:1305-1326，与原基线逐字一致 | OSError 仍变成 RuntimeError，日志仍误标锁不可用；ValueError 原异常对象传播、无该 warning，锁可再获取。开放 |
| BUG-18 | `_iter_paths` 移至 store.py:410-420，函数与原基线逐字一致 | z-seed/a-runtime 选择 seed；a-seed/z-runtime 选择 runtime。来源优先级仍受字典序影响。开放 |
| BUG-02/03/04/11/12/13a-c/15 | client.py、errors.py、fallback.py、config.py 的完整文件与原基线一致；工作树与当前 HEAD 一致 | 保留 rev2 的 R 级证据；本次只核对源码存续，没有重跑这些条目的完整动态对照 |
| BUG-09/13d | retriever.py、config.py 与原基线一致 | 仍为 H；没有补成并发可达性或业务影响的证据 |

本表记录 rev3 时点，不能当作 rev4 当前开放状态。相关历史回执见 §9，外部独立复核的来源与覆盖差别见 §9.1；七项修复与本轮发现以以下 §0.4 为准。

### 0.4 rev4 本地修复状态：七提交已存在，两项尚未完成

七提交均存在，父子顺序连续，最终 HEAD 为上述 rev4 快照。独立核验读取了源码与测试 diff，并从该 HEAD `git archive` 到临时目录，明确确认 config/client 的导入来源后运行 17 个相关测试文件（含七个新增回归文件）。结果与限制见 §6.1。

| 提交 | 工作包/条目 | 核实的本地行为 | rev4 状态 |
|---|---|---|---|
| `b1b2771b9` | WP1：02/03/04 | 新流错误异常区分 HTTP/provider code；GLM 1302/1311/1113 分类；Anthropic/Google error 显式失败 | L，所覆盖离线契约通过；完整上层结算/live 另验 |
| `cbca2b4cf` | WP2：01 | 业务 OSError 原对象传播，取得锁/业务/unlock 分别处理；日志断言有回归 | L，所覆盖离线契约通过 |
| `3fc0972e7` | WP3：11/12/15 | 累计 usage 更新；重试重置 accumulator；reasoning-only 不再同模型静默重试，真正空响应仍重试 | L，所覆盖离线契约通过；不据请求次数推定真实收费 |
| `1cf011e93` | WP4a：18 | seed→runtime 按来源显式覆盖，两种目录次序与回退回归 | L，原排序反例已修正；T2 与部署状态分别验收 |
| `b8553384c` | WP4b：13a-c | 非法布尔 default、引号内 # 与进程环境小数 timeout 用例通过 | 13a/c：L；13b：部分修正，新 mapping 来源回归为 R/P2，开放 |
| `9a9abcce9` | WP4b-2：05 | 候选先于 limit，堆保留有界 top-k，同 ts 按行序选择 | L，原物理截断反例已修正；时间戳口径、读取成本仍按原验收边界核对 |
| `077eca97b` | WP4b-3：07 | 路由声明/拨号观测分字段，状态不再触发发现，地址去 userinfo/query | 部分修正；连续构造后保留旧拨号观测为 R/P2，开放 |

**未处理项校准**：BUG-13d 指全局 `_fallback_notes` 的并发隔离，不是“write 失败重排序”；BUG-09 才是向量缓存并发待证项，两者继续按 §7.2 复核。BUG-08 已有此前 MethodStore T2 本地修复资产，且本轮运行了其 durability 测试文件，不能与 BUG-09 合并标成 H；完整资格与 live 状态仍没有本轮结论。若“write 失败重排序”另指其他机制，须另附源码、触发序列及影响证据，不能覆盖已有编号。

BUG-06、14、16 的治理/契约核对、BUG-17 存量静态债、§8 安全覆盖矩阵仍不因这七提交而关闭；BUG-10 维持 X。没有新增 Method efficacy 或部署证明。§1–§5 中的原故障描述用于保留复现与回归依据，不表示这些历史输入仍在当前 HEAD 失败。

## 1. 原 P0 的勘误与真实缺陷

### BUG-01｜锁内 OSError 被误当作加锁失败，二次 yield 替换原异常

**依据**：`src/llm_loop/core/session.py:1305-1326`；调用方 `session.py:1443-1456`。

原报告给出的 `_SHARED_FILE_LOCKS`、`_acquire_fcntl` 示例不是该基线的真实源码；实际 non-POSIX 回退还使用了 `_fallback_locks_guard`。原报告以“yield 位于 try 内”推导协议违规也是错误的。[Python contextlib 文档](https://docs.python.org/3/library/contextlib.html#contextlib.contextmanager)明确允许用 try/finally 包住 yield，以确保清理资源。

真实结构如下：

```python
try:
    with open(lock_path, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
except OSError as exc:
    logger.warning("共享文件锁不可用（fail-open）: %s: %s", lock_path, exc)
    yield
```

**复现**：在 with 主体抛 `OSError("body-failure")`，异常回到第一次 yield，释放锁后落入外层 except，再 yield 一次；contextlib 抛 `RuntimeError: generator didn't stop after throw()`。with 主体仅执行一次。ValueError 对照原样传播，之后锁仍可再次获取。

**实际影响**：`set_shared_current_session` 只捕获 OSError，原本应走 fail-open 的磁盘写入失败可能变成未捕获 RuntimeError。业务 OSError 同时被 warning 归因为“共享文件锁不可用（fail-open）”，使观测者误判故障来源。**已证实异常类型与日志归因失真；没有证实死锁或互斥失效。**

**修复边界**：将“资源取得失败”的处理限制在 open/flock 阶段，确保整个上下文只 yield 一次；业务异常不得被加锁 fallback 捕获。清理阶段如有独立故障，应保留原异常事实，不把业务磁盘错误标为锁不可用。是否继续采用加锁失败时 fail-open，需沿现有契约审查，而不是顺手改变。

**验收**：以下断言独立检查，不能仅用“最终没有 RuntimeError”判通过。

- 正常释放；业务 OSError/ValueError 保留原异常对象、类型与内容，with 主体只执行一次。
- **日志归因**：锁已正常取得时，主体 OSError 不得产生“共享文件锁不可用（fail-open）”或加锁失败事件；在需要记录业务失败的真实调用方，归因为业务操作失败。
- open/flock 失败仍按现有加锁失败契约处理，锁故障日志与业务日志可区分；unlock 失败记录为清理阶段故障，不得覆盖正在传播的业务异常事实。
- 跨进程后续获取、非 POSIX 回退及真实调用方的失败处理符合既有契约。

## 2. P1：流式协议与错误分类

### BUG-02｜429 状态不能单独决定错误原因和 fallback 范围

**依据**：`src/llm_loop/core/loop/engine_services/fallback.py:98-123,411-420`；`src/llm_loop/llm/errors.py:153-175`。

离线向现有分类函数传入 HTTP 429，body 分别带 GLM 业务码 1311、1302、1113，三者均得到 `eligible=True` 与“429 限流”。

[智谱官方错误码](https://docs.bigmodel.cn/cn/faq/api-code)将 1311 定义为当前订阅未开放所选模型权限、1302 定义为速率限制、1113 定义为账户欠费；HTTP 429 还承载其他额度与套餐状态。因此缺陷是**分类与文案丢失了业务语义**。

原报告有两项过度推断：

- 1311 针对所选模型，不能推导“换任何模型都失败”。另一个有权限的模型或独立账户/provider 可能可用。
- 实际发出请求不等于请求一定计费；全链是否失败、各失败请求是否收费，必须看实际候选身份与 provider settlement。

**建议**：先保留 HTTP status、provider 身份、业务 code/type、经脱敏的错误摘要，再产生有依据的语义分类。区分“同身份重试”“同账户其他模型”“独立 provider fallback”；模型权限错误不能默认归为瞬时服务可用性错误，未知业务码仍应如实反馈，不凭关键词推断全局权限。

`is_quota_error` 与 availability fallback 回答不同问题，布尔结果不同本身不构成矛盾。应保证它们消费同一份事实，而不是合并成一个丢失维度的布尔值。

**验收**：至少覆盖 1302、1311、1113、未知业务码、403、5xx、SSE 错误，以及 strict override 不被静默换模型。先用离线 fixture；确需 live smoke 时按已确认偏好使用 GLM-5.3，不能把审查改写自动变成真实模型消耗授权。

### BUG-03｜SSE provider 业务码污染 HTTP status_code

**依据**：`src/llm_loop/llm/client.py:2021-2023,2747-2774`；`src/llm_loop/llm/errors.py:28-36`。

真实函数名是 `_check_sse_error`。它给观测器分别传入真实 HTTP 状态与 provider code，却在异常对象上使用 `status_code=int(error.code)`；非数值业务码回退成 500。

**复现**：HTTP 200 的 OpenAI 兼容 SSE 含 `{"error":{"code":1311,"message":"model unavailable"}}`，抛出 `LLMHTTPError(status_code=1311)`。BUG-02 的 `status_code >= 500` 也会把 1311 当作可降级服务错误。因此“HTTP 1311”日志不能当作真实 HTTP 状态。

**修复边界**：保留 HTTP 200 与 provider code 1311 两个事实，并明确“流内失败”这一事件层级。可扩展现有异常或使用专门的流式 provider 异常，但所有分类、反馈、journal 与调用方必须同步，不能只把 status 改为 200 导致上层误认成功。

原报告修复示例读取 `exc.provider_code`，但原基线 LLMHTTPError 并无该字段；必须连同异常构造契约更新。rev4 已核实 WP1 新增该字段与专门流异常，原签名缺口不再作为当前开放事实。也不能继续只保存 message 而丢失可解析的业务码。

**验收**：HTTP 200 + 数值/字符串/缺失业务码、普通非 2xx 响应、观测器与抛出异常的同一事件对应、分类结果及 settlement 终态一致。

### BUG-04｜Anthropic/Google 流内 error 未上抛，部分内容被当作正常响应

**依据**：`src/llm_loop/llm/client.py:2265-2333,2396-2449`。

两条解析路径都处理正常内容，但未处理流内 error 对象。正常迭代结束后会进入 `_note_settled_response_facts` 与 `_finish_response`。

**复现输入与结果**：

| 协议 | 模拟输入 | 实际返回 |
|---|---|---|
| Anthropic | text_delta="partial"，随后 type=error / overloaded_error | content="partial"，finish_reason=""，truncated=false |
| Google | candidates text="partial"，随后 error.code=503 / UNAVAILABLE | 同上 |
| OpenAI 对照 | partial text 后 error.code=1311 | 抛异常，但 status 被业务码污染（BUG-03） |

[Anthropic 流式文档](https://platform.claude.com/docs/en/build-with-claude/streaming)明确列出了流内 error 事件。Google 用例证明 LFL 对上述兼容响应的行为，**本次未向官方 Google 服务验证其实际发生频率**。

**修复边界**：各协议按自身 error schema 显式上抛，保留已投递 partial 的不完整事实与 attempt 身份；不得把“已有文本”作为流成功的依据。对正常 EOF、协议 terminal event 与 provider failure 的区别也应建立测试。错误后不能发布成功 completion 或执行不完整工具草稿。

**验收**：零输出 error、partial 后 error、未知事件、正常终态、缺失终态、工具 arguments 半截；核对上层 run 与 provider attempt 的失败结算。部分内容已展示时不得重放造成重复工具执行。

## 3. P2：检索、计量、配置与存储

### BUG-05｜通用 JSONL 查询提前截断导致后续命中不可达

**依据**：`src/llm_loop/introspection/search.py:117-168,285-395,407-425`。

`_jsonl_search` 在文件正向扫描中收集到 limit 条即 break。两条同词记录按 old→new 写入，limit=1 时只返回 old。这证明位置偏置，**不证明所有任务都应以“最新”为最佳答案**。

原报告把该行为推广到 memory、method 等全部检索路径不成立：memory/experience/episode 有对象型专用路径，method 在 `search.py:742-789` 使用词法检索及可选 RRF；`MethodStore.list` 自身有相关性排序。

**建议**：先按 kind 定义默认检索契约：精确 ID 优先、相关性查询、按时间查看、事件顺序复盘分别处理。对需要 newest/top-k 的 kind，排序或候选选择必须早于输出 limit；append-only 大文件应采用有界 top-k 或索引，避免无条件把整文件载入内存。kind=all 的跨类结果截断同样需要公平性与可分页性检查。

**验收**：超过 limit 的同词记录、倒序/同 timestamp、无 timestamp、精确 ID、损坏尾行、大文件内存上界与翻页；专用 memory/method 检索不回退。

### BUG-06｜旧函数尺寸机制的文档契约漂移，不能归因所有功能漏检

**依据**：`tests/unit/test_arch_guards.py:44-46,74-78,648-675,721-739`；`scripts/r9_commit.sh:99-143`。

复核确认：注释点名的 `test_function_lines_ratchet_within_baseline` 没有对应测试定义；基线文件实际名是 **function_size_baseline.json**，不是原报告的 functions_size_baseline.json。

但同文件已写明，历史函数尺寸分类器只用于诊断/合成夹具，**不再对真实源码形成 CI 形状门**。因此缺测试至少是注释漂移，不能未经契约裁决就要求恢复“每个函数零增长”硬门，更不能据此解释 SSE、配置、锁异常为何漏检：尺寸与这些行为契约没有已证明的因果关系。

`test_baseline_ratchet_not_raised` 比较当前文件与 HEAD。在普通工作区可检测未提交基线改动；R9 wrapper 则先生成 PROBE commit，再在该 commit 的隔离树运行测试，HEAD 就是候选自身。此时该比较无法独立证明前驱到候选的基线没有增长。提交前缀保护能提供变更可见性，但不能替代数值不回退证明。

**建议**：先明确哪些字段仍承担强制门禁、哪些仅诊断，删除或修正过期注释。对仍属强制项，用可信前驱完整 SHA 或 CI 的可信 merge-base 比较，并验证缺少基准/多父提交情形；不能把“tag”天然视为不可移动的信任锚点。后续静态诊断 ratchet 是另一个契约，见 §6，不自动证明旧尺寸比较已修复。

**验收**：在 PROBE 提交态上注入仍属强制范围的违规，必须失败；诊断范围不应驱动无意义拆函数；缺基准与工具失败不得静默假绿。

### BUG-07｜配置存在明确层次，effective 路由与实际拨号地址仍需区分

**依据**：`src/llm_loop/config.py:151-183`；`src/llm_loop/factory.py:1488-1515,2609-2629`；`src/llm_loop/llm/providers.py:306-326`。

dotenv 明确采用进程环境优先；status 也保留 configured 与 registry effective 字段，并提供 scope/source。不同层的模型名不同，**不能单独证明三源冲突或无优先级仲裁**。原报告中的三组运行配置没有实例、run、时间与请求回执绑定，本版不将其当作现行生产事实。

可确证的窄缺口：`_effective_model_status` 返回 registry 的 `provider.base_url`；local provider 的 `client_params` 可以发现动态 llama-server 后改写实际 base_url。因此状态只展示路由声明，未完整表达实际拨号事实。

**建议**：区分 configured、resolved route、attempt 的 dial target；实际连接事实来自已经构造/调用的 client 或 transport receipt，不为查询状态再次触发服务发现。输出只能包含无凭证地址与来源，不泄露 api_key 或 URL 中的鉴权参数。

dotenv 跳过非法行与文件读取失败，是单独的可观测性改进项；可记录行号/键名/失败类别，不能打印原值或秘密。

**验收**：环境覆盖 dotenv、runtime/run override、local 动态端口、发现失败回退、状态查询无新副作用、保密字段不泄露。

### BUG-08｜MethodStore T2 已有后续本地修复，不能继续写成当前完全无锁

原 release `src/llm_loop/methods/store.py` 的 qualification/journal append 与状态写入未提供完整的单写者、原子提交和耐久性结果分型。这是应修复的 storage 契约；“649 个 candidate”不是实际并发写入频率证据。

本次复核期间已看到本地提交 **26c738076d3df7b42a760d3742bcbf03f6eb0eb2**，新增 flock/进程锁、提交写入路径、结果分型、调用方反馈，并新增 `tests/unit/test_method_store_durability.py`。不得重复开展同一改造，也不得把旧行号当新实现位置。

**状态**：本地修复资产已存在；本次没有独立重跑其完整资格流程、没有重新验证部署，所以不称“本轮已上线验收”。

**后续验收重点**：create-if-absent、RMW/CAS、journal append 的不同语义；temp write/fsync/rename/dir fsync 各失败窗口；明确拒绝与 commit uncertain；跨进程同 ID 并发、readback、工具回执能表达未确认结果。不能把所有写入统称为“tmp+replace”或默认写入失败可安全重试。

### BUG-09｜向量缓存锁覆盖不全：保留为待验证竞态

**依据**：`src/llm_loop/memory/retriever.py:498-515,1293-1316`。

持久化合并在 `_cache_state_lock` 中执行 cache.clear/update，但 single-item embedder 的后台预热分支在锁外写 `cache[vector_key]`。这足以提出同步覆盖疑点，尚不能证明“多子代理必然丢检索命中”。

**验证方向**：先证明同一 retriever 实例、同一 cache 对象上有两个可并发到达的写/flush 路径，再用 barrier 固定写入与 clear/update 顺序，观察向量是否丢失、dirty 检测是否漏持久化。进程间磁盘合并锁与进程内 dict 锁分开测试。未完成之前不计入已复现缺陷数。复核期限及证据不足时的退出规则见 §7.2。

### BUG-10｜“首窗口截断”引用无关，撤回

原指针 `memory/retriever.py:1148-1151` 实际是 semantic_fallback_reason、semantic_latency_ms、query_embedding_ms 诊断字段，没有 max_items 或分页窗口判断。本次未找到支持原断言的路径。应补齐 producer、页 offset、输入和期望结果后才能重新登记，不能凭报告短语寻找相似代码来延续原结论。

### BUG-11｜Anthropic 最终输出用量漏读

**依据**：`src/llm_loop/llm/client.py:2277-2282,2321-2326`。

message_start 的 output_tokens 被写入 accumulator，而 message_delta 只更新 stop_reason；[官方文档](https://platform.claude.com/docs/en/build-with-claude/streaming)说明 message_delta.usage token counts 是累计值。

**复现**：message_start.output_tokens=1，message_delta.output_tokens=15，正常 end_turn，最终 response.completion_tokens=1。

**修复与验收**：按协议更新累计计量，不相加重复累计；缺字段不得清零；核对 input/output/cache usage、流式 telemetry 与最终 response；多个 usage 事件和错误终态均有测试。该缺陷证明 response 用量失真，不直接证明所有全链成本账本都同样失真。

### BUG-12｜重试共用 accumulator，truncated 标志残留

**依据**：`src/llm_loop/llm/client.py:1980-1988,2132-2136,2151-2175`。

**复现**：第一次仅收到 finish_reason=length、没有 text/reasoning/tool delta，随后断连；允许无输出重试。第二次返回文本 ok、finish_reason=stop，最终仍 truncated=true。

**修复边界**：一次 transport attempt 的 response accumulator、工具聚合与 finish/truncation 状态须重新初始化；失败 attempt 的 usage/transport 事实仍保留在 attempt journal，不通过丢弃记账换取最终响应干净。

**验收**：上述序列、usage-only 后断连、已有 text/reasoning/tool 草稿时不重复投递、成功终态 flags 一致。

### BUG-13｜配置解析子项分别处理

| 子项 | 固定基线依据 | 本轮结果 | 修订结论 |
|---|---|---|---|
| 13a 非法布尔默认值 | `config.py:188-197` | default=True、值 typo，实际 False | 非法值应回退传入 default，并继续记录告警 |
| 13b 小数 timeout | `config.py:1051`、`_env_int:103-111` | "0.5" 回退为 120.0 | 是拒绝小数字符串后回退，不是把 0.5 截断为 0；若契约支持小数应使用 float parser |
| 13c 引号内空格 # | `config.py:178-183` | `X="abc #def"` 得到含前导双引号的 `"abc` | 解析器未区分引号内字符与注释；没有空格的普通 # 不受该 split 影响 |
| 13d 全局 notes | `config.py:77,80-84,866-868` | 未做并发调度复现 | 需先证明并发 load_settings 可达；不能把装配单线程场景夸为实时配置失效；复核期限见 §7.2 |

**验收**：合法/非法/空值布尔、小数和整数字符串、单/双引号、带空格与不带空格的 #、dotenv 环境优先、告警不泄露原值；notes 如需隔离则测试两个 mapping 的互不污染。

### BUG-14｜retry_disconnect 的协议覆盖不一致，需先明确承诺

OpenAI 在 `client.py:2159-2175` 消费 retry_disconnect；Anthropic/Google 在各自异常捕获中直接上抛。原标题“三协议下均失效”与源码不符。

需要核对公开配置是否承诺跨协议相同行为。若要补齐，仅允许在零 text/reasoning/tool delta 投递的条件下重试，保持取消、attempt 结算和总预算契约；已有部分输出时应交给模型或操作者决定恢复。协议功能差异不能自动升级成 P1。

### BUG-15｜reasoning-only 的空响应重试不满足“零 delta 投递”前提

**依据**：`src/llm_loop/llm/client.py:1711-1773`，空判据只看 content/tool_calls。

**复现**：第一次输出 reasoning=r1、无正文与工具；第二次输出正文 ok、reasoning=r2。外层产生两次 mock 请求，消费者先后收到 r1、ok、r2。该路径的“空响应保证零 text/tool delta”注释没有覆盖已展示 reasoning。

**建议**：明确 reasoning-only response 是否属于可自动重试的空响应；展示侧保留 attempt 边界，避免把两次思考拼成一个成功回答。每次请求的 usage 与 settlement 分别记录，再汇总 whole-call；不能把已发生的 provider 请求或 reasoning 投递抹掉。

本轮没有证明同一段 thinking 被逐字重复，也没有测量实际收费，撤回“必然二次计费”的说法。

### BUG-16｜重试字段与时间预算要区分不同层级

`client.py:851` 声明 max_retries，本次未见该 client 路径消费；实际 transport 重试使用 retry_disconnect，空响应重试使用独立常量。应明确字段是有效 API、兼容残留还是待移除字段，不应再新增第三套含糊预算。

`_stream_total_deadline` 在每次 transport attempt 内创建（`client.py:73-82,2008`）。这证明 stream 时限按 attempt 计算，**没有证明已定义的 whole-call/run deadline 被违反**。先追溯 timeout 配置、上层 run 时限与 journal，再决定是否增加跨 attempt 累计时限。

**验收**：mock clock 覆盖 connection/read/stream/whole-call 不同 deadline、重试 backoff、取消与嵌套 fallback；预算超时事实可归因到具体层，而非统一报“网络不可达”。

### BUG-17｜静态债必须绑定扫描范围、工具版本与工作目录

固定 release，Ruff **0.16.5**，在 release 根目录运行：

| 范围 | exit | 诊断数 |
|---|---|---|
| `ruff check src --output-format=json` | 1 | 30 |
| `ruff check src tests scripts --output-format=json` | 1 | 67 |

src 分布：E402×9、SIM105×5、I001×5、UP035×3、UP032×2、UP037×2、SIM102×2、F401×1、F841×1。原“28”遗漏了固定基线的两个 SIM102，也没有说明 scope。

使用绝对扫描路径并强制 --config 曾得到不同计数；该调用并非 CI 同口径，已排除。以上表格以 release cwd、相对 scope 的回执为准。

src 的 F401 位于 `browser/attestation.py:27`，F841 位于 `browser/perception.py:1720` 的 document_hash。未用变量是审查线索，**不是逻辑写漏的证明**；需看其职责与调用方。

新 CI ratchet 已有本地提交，见 §6。静态债不与本次修复混成大提交，不通过扩大基线或批量机械重排来消除红色外观。

### BUG-18｜新增：同 ID 的 seed/runtime 优先级依赖目录字典序

**依据**：`src/llm_loop/methods/store.py:236-246`。

代码注释要求 runtime copy wins，但实际将两类路径整体 sorted 后用后者覆盖。隔离目录 z-seed/same/METHOD.md 与 a-runtime/same/METHOD.md 中，`_iter_paths` 选择 z-seed。该错误在默认目录下可能不出现，但自定义目录是明确的输入条件，不应只用注释固化偶然排序。

**建议**：各来源内部确定性排序，再显式 seed→runtime 覆盖；优先级由来源身份决定。后续 MethodStore T2 提交不应被假设已同时修复这个独立问题。rev3 在 `db378621` 的 store.py:410-420 核实函数未变，并复现两种目录次序（§0.3），当时仍开放并单列到 §7 工作包 4a。rev4 的 `1cf011e93` 已修正此反例，状态见 §0.4；T2 验收与本项验收仍分别记录。

**验收**：runtime 路径分别排序早于/晚于 seed、同 ID 不同内容、runtime 删除后回退、精确水合与宽检索保持一致。

## 4. 能力改进：从“存在”走到“实际有益”

### 4.1 Method：存在闭环入口，实际发现与收益证据仍不足

原报告记录的 runtime pool 为 682，candidate=649、hold=28、retired=2、qualified=1、active=2；这些状态合计为 682。原 usage 与 qualification 数值保留为**原会话快照**，本次未重新读取实时库；不能将其称为当前 live 计数。

| 表面/机制 | 代码事实 | 不能据此推导 |
|---|---|---|
| Task 方法检索 | `MethodStore.list:452-524` 仅排除 retired；semantic_candidates:537-549 同样保留 candidate；`search.py:742-789` 接入检索/水合 | 模型只能看见 active+qualified 的 3 张 |
| Learning 去重视图 | `factory.py:1692-1723`、`reflection.py:312-345,383-414` 仅展示 active/qualified | 所有语义检索都过滤 candidate |
| 反思生产 | `reflection.py:510-523,573-578` 只产 candidate | 系统没有 qualification 入口 |
| 显式资格与迁移 | `registry_experience.py` 定义 record_qualification/refine_method；store:654-684、830-859 要求独立 episode 与 promotion=pass | Learning 必须自动宣布自己产出的卡有效 |
| 开场注入 | `method_injection.py:1-11` 退役旧 ACTIVE 清单，保留检索入口与回记提醒 | 任何提示或实验机制都不存在；应无证据恢复旧清单 |
| blocked_transition_attempts | `knowledge_health.py:186` 统计 blocked journal 行数 | 0 代表从未晋升、从未尝试或链路从未走通 |

`with_qualification` 在 `knowledge_health.py:153-154` 统计资格文件是否存在，**不是 promotion pass 数量或通过率**；“67 有 qualification、1 qualified”并不矛盾。指标可增加清晰注释，而不是把原有文件存在性计数偷换为通过计数。

**建议顺序**：

1. 先测量真实路径：曝光/搜索→精确水合→适用性决策→record_use→独立 qualification→迁移。记录发生时间与目标工具调用的先后、决策类型、episode/Method ref、失败与未确认写入；区分“方法条数”“决策次数”“任务机会数”，不用 usage 声明直接代替真实行为证据。
2. qualification 的通过、失败、不足、未评估，以及迁移请求/成功/blocked/persist-uncertain 分别呈现。说明收集窗口、是否覆盖 seed/runtime、文件解析失败与数据完整性；只有分母同口径时才算转化率。
3. candidate 的去重发现与“建议执行该方法”分开设计。若扩充 Learning 去重，可展示 candidate 的低权威摘要以避免重复产卡，但不能自动赋予已验证资格，也不能挤占有用 top-k；用重复产卡率、召回率与反思成本验收。
4. 如要在工具调用前增加轻量方法提示，先检查现有表面与默认开关，给模型自主展开、拒绝和绕过的入口。先验证目标任务的可发现性，再独立验证真实收益；不要恢复已经有干扰证据的开场大清单。

**实验边界**：[Method subject-binding v3 结果](RESULT-20261006-method-binding-v3.md)为 EFFICACY_NOT_QUALIFIED，production_promotion_authorized=false。strong net=2、negative_flip=2；weak net=2；没有达到冻结阈值。该结果不能证明全部 Method 无效，也不能被本报告覆盖为“建议立即默认开启”。

重新开线需满足原结果文档中的遥测修复、全新 holdout/SPEC 与明确授权。未来实验优先弱模型的正确率、少出错重来、FCR 与 whole-run wire 成本；强弱模型分层报告，不以更少工具次数替代任务质量。

### 4.2 上下文：先统一事实来源，再验证工具渐进暴露的净收益

原报告摘要写 56.7%，明细却是 19,794 / 37,473 ≈ **52.8%**；应以明细算术为准，并标为原会话估算。

`core/history.py:1748-1758` 的 breakdown 使用 chars//2；`token_budget.py:154-189` 的预算优先采用 tokenizer 实测，否则使用投影密度。engine:1063-1082 已接入可选 schema token counter，client:940-990 也提供本地 template/tokenize 计量能力。因此两值不同**不自动证明预算低估真实 token 30%**，更不能要求把所有 provider 强行统一为同一 chars_per_token 常量。

原会话 schema 估算差异为 19,794 / 15,214 - 1 ≈ 30.1%，但尚缺 tokenizer/actual usage 真值来判定哪一方偏差。建议统一**来源契约与标签**：actual、tokenizer measured、density estimated 各自标注 model/provider、schema surface hash、request/attempt 身份；展示估算不能冒充准入真值。

还需纠正两个分母问题：

- schema 占“当前实际输入”的 52.8%，不是占 184,000 输入预算的 52.8%；按 19,794 估算仅约 10.8%。小会话的高比例不等于历史容量已耗尽。
- 模型标称 1M、输入预算 184k，可能来自模型/provider/operator/run 的有效限制或预留；没有来源链证据，不能称“刻意压低”。

**工具渐进暴露建议**：先衡量当前工具投影/发现能力、冷启动与长任务成本，再验证 schema 压缩、按需水合或工具搜索。不能机械地按用户文本推断任务类别后隐藏可能必需的工具。工具注册面、provider surface、discovery 与调用授权仍须一致，hydrate 后还要能真正调用。

收益用实测 schema token、whole-run input/output/cache wire、FCR、失败/重试、首个有效动作延迟与新检索开销计算。动态 surface 会改变 prefix/cache；省 schema 不保证总成本下降。**撤回“直接释放约 50% 上下文”“schema 完全无任务价值”两项承诺。**

### 4.3 执行可靠性：错误事实与成功回执必须先可信

优先统一 transport、provider 和 attempt 事实，而不是加更多提示文案：

- 响应 HTTP 状态与业务码独立保留，分类和用户反馈消费同一事实。
- 已展示部分输出仍可属于失败 attempt；终态 completion 与 run.end 不可因此写成成功。
- 取消/重试/fallback 保留各自身份、成本与失败事实，成功响应不继承旧 attempt flags。
- 持久化结果区分明确成功、明确失败、提交结果未确认；未确认时先 reconcile，不盲目重复写入。

这些是模型正确判断与恢复所需的事实基础，不由程序替模型决定任务语义或完成度。

## 5. 撤回与限缩记录

| 原断言 | 本版处置 | 理由 |
|---|---|---|
| yield 在 try 内导致死锁 | 撤回归因，保留 BUG-01 的真实二次 yield | 官方协议允许 try/finally；本轮锁可再获取 |
| 1311 换任何模型都失败，每笔均计费 | 撤回 | 权限可能只针对该模型；收费需真实回执 |
| 方法库整体仅 3 张可见 | 撤回 | Task 通用检索保留 candidate |
| blocked=0 证明没有任何晋升尝试 | 撤回 | 指标仅统计 blocked journal |
| Learning 无 promotion 输出就是系统闭环不存在 | 限缩 | 显式 qualification 与生命周期入口已存在；自动生产与独立验证不同 |
| 5 个 worktree 证明五次实验都未收敛 | 撤回 | 目录存在不能证明实验结果，应读冻结数据与终局文档 |
| 尺寸门禁解释所有功能 bug 漏检 | 撤回因果 | 尺寸检查与流协议/异常语义没有已证实因果链 |
| config/runtime paths/providers 零直接测试 | 撤回 | 存在 test_config、test_runtime_paths、test_providers，并直接 import 被测模块 |
| runtime/memory.py 的覆盖结论 | 撤回引用 | 该基线路径不存在；需重新定位真实模块 |
| mock e2e、默认排除 real_llm 就是无效门禁 | 撤回泛化 | mock 可验证契约；真实 provider 属不同测试层，须说明独立资格回路 |
| except Exception 有意 fail-open，所以基本无问题 | 限缩 | 注释只说明意图；仍需验证影响、告警、授权与恢复契约 |
| retriever 首窗口截断 | 撤回 | 原指针只指向 diagnostics，没有分页代码 |
| 所有 schema 成本都无任务价值 | 撤回 | 工具定义提供调用能力；优化需要净收益证据 |

原报告关于“LLM client 内没有 HTTP 429 退避重试”的窄结论可保留：`client.py:2157-2179` 中 HTTPError 原样上抛，transport 断连另有重试/backoff，空响应还有独立重试。不能泛化为“整个系统无重试或无 backoff”。

## 6. 测试与质量门禁：全绿含义、既有更新和剩余缺口

原审查报告称：

```text
7738 passed, 107 skipped, 24 warnings in 84.49s [exit=0]
```

本次未取得对应运行命令、环境、candidate tree 与完整收集清单，也未重跑，因此该数字只作为**原报告提供的历史回执摘要**。它不能证明每个 BUG 的触发条件被测试，更不能支持“所有缺陷都已确证且无一被覆盖”。

复核已找到：
`tests/unit/test_config.py:10-37` 直接测试 load_settings，
`test_runtime_paths.py:3-23` 直接测试路径绑定，
`test_providers.py:19-20` 直接引用 Settings/load_registry。
“存在这些测试”同样不证明本文的新 edge cases 已覆盖；应以具体断言与负例为准，而不是测试行数比例。

**新本地治理状态**：提交 **20be00979d72d6c0dea5f3fd2f19044ddf61efdb** 引入 `scripts/check_static_diagnostics.py`、冻结静态债台账、门禁负例与 CI 接线。其设计见 [R9 静态诊断 ratchet](DESIGN-20261008-r9-static-diagnostic-ratchet.md)。本次核实提交与文件资产存在，未独立复演其整套提交门禁；原尺寸机制的问题不能因此宣布全部关闭。

**推荐验证分层**：

| 层 | 验证目的 | 本报告相关用例 |
|---|---|---|
| deterministic unit / MockTransport | 协议与异常边界可重复、零真实消耗 | BUG-01/02/03/04/11/12/13/15 |
| 隔离文件与并发故障注入 | 原子性、耐久性、结果未确认与路径权威 | BUG-08/09/18 |
| 候选树门禁 | 真实 staged/isolated candidate，不测旧 HEAD | 静态诊断新增拦截、契约回归、全量 suite |
| provider qualification | 真实协议/参数与计量差异 | GLM-5.3；其他协议在确需支持时各自资格化 |
| production smoke/currentness | desired generation 与 live 实例、来源、结果结算一致 | 发布后独立验证，不凭 main HEAD 推定 |

负例必须证明“错误会被拦住”，正例必须证明“正常响应/恢复仍成功”。静态债、skip、环境错误与业务失败分别报告。浏览器或真实 provider 无运行条件时写明未验证范围，不用单元测试绿灯替代现场验收。

### 6.1 rev4 独立验证与外部总结的边界

| 证据来源 | 结果 | 本轮可确认的范围 |
|---|---|---|
| 用户提供的 LFL 修复摘要 | 6686 passed / 107 skipped / 0 failed，起始 6640；逐包先红后绿 | 本轮未取得对应完整命令、收集清单与逐包红态回执，未独立重跑全量；保留为外部运行摘要 |
| 独立隔离候选，首次运行 | 269 passed / 1 failed / 3 warnings | 新增 timeout 测试只设置 key/timeout，缺必填 LLM_BASE_URL；失败是 fixture 环境依赖，不是该缺陷红态证据 |
| 同一隔离候选，补齐显式占位配置后 | **270 passed / 3 warnings，pytest exit=0** | 17 个相关文件、七个新增回归文件均在所列 fixture 下通过；没有修改候选源码或测试 |
| 独立 Ruff 0.16.5 | **18 个改动文件，0 诊断，exit=0** | 候选根目录、相对文件 scope；不代表全树历史债消失 |
| 独立补充边界对照 | **BUG-13b mapping 与 BUG-07 连续构造均不符合来源/时效契约** | 确认两个仍开放的 R 级缺口，详见 §7.3 |

补齐的测试配置是无网络占位值：LLM_BASE_URL=https://audit-fixture.invalid/v1、LLM_API_KEY=占位 key、LLM_MODEL=audit-fixture；数据路径与 pytest basetemp 位于隔离目录。默认排除 real_llm，相关 provider 行为均为 mock。首轮失败揭示新增测试依赖外部环境，应将必填占位配置收进测试 fixture；不能以本机已有真实配置代替测试自包含性。

270 项全绿与补充反例不矛盾：原测试只验证进程环境 timeout，未覆盖 mapping/进程冲突；拨号测试每例清空观测，未覆盖“先成功改写、再发现失败回退”的连续序列。全绿证明所执行断言通过，不证明这些新反例不存在。对“先红后绿”的历史顺序，本轮只确认版本化回归资产及当前结果，不替外部缺失的逐阶段回执背书。

## 7. 执行路线与验收矩阵

本节是后续建议，不授权自动实施全部行为修改。每阶段单一职责、独立 candidate、遵循维护手册；不与当前 ArchiveStore/DRC 工作互相覆盖。

### 7.1 执行前重新 pin，工作包分别验收

每包开工先记录完整 HEAD、候选树、目标函数位置及相关工作树变化，按冻结输入复跑该包的负例/正常对照，登记“仍存在／已有修复待验收／不可达／证据不足”。§0.3 的快照不能代替开工检查。最终验收绑定实际 candidate；发布后的 release/live 另取来源与 generation 证据。

BUG-03 的业务码污染会影响 BUG-02 分类，工作包 1 应先确定统一错误事实契约，再同时验收分类与流终态。BUG-18 是来源优先级问题，与 T2 写入耐久性分别验收。下表保留原工作包顺序；rev4 已落地的实现与未通过的边界以 §0.4 为准，当前先追补 §7.3 两项，再做最终候选/集成验收。

| 顺序 | 工作包 | 验收出口 | 停止/回退条件 |
|---|---|---|---|
| 1 | 流错误与错误事实：BUG-02/03/04 | 不同 HTTP/provider 语义分类准确，partial+error 失败结算，strict override 保持 | 事实丢失、正常流误报、模型权限被全局推断、重复工具副作用 |
| 2 | 共享文件锁异常传播：BUG-01 | 单次 yield，业务异常原样，日志区分业务/取得锁/清理故障，调用方 fail-open/fail-closed 符合既有契约 | 异常类型或日志归因变化、资源泄漏、非 POSIX 回退失效 |
| 3 | attempt 状态与用量：BUG-11/12/15，核对14/16 | 成功响应 flags 干净，各 attempt 用量/部分输出不丢，恢复预算清晰 | 已输出仍自动重放、旧成本消失、取消或 deadline 越界 |
| 4a | Method 来源优先级：BUG-18，独立候选与回归 | 两种目录次序均由 runtime 覆盖 seed；删除回退、精确水合/宽检索一致，兼容 T2 耐久性资产 | 再依赖目录字典序、候选遮蔽规则改变、与 T2 写入语义相互回退 |
| 4b | 配置与检索窄修：BUG-13a-c、05、07，分别成包 | 明确输入/排序/有效路由契约，正常路径及大文件上界不回退 | 全局行为被无证据重排、动态发现副作用、敏感字段泄露 |
| 并行收尾 | 既有 MethodStore T2 与 CI ratchet | 使用已提交资产做其既定验收，区分本地资格与 live 生效 | 旧报告触发重复改造、提交/部署身份漂移 |
| 后续研究 | Method 路径遥测与 schema 净收益 | 先闭合分母、来源、真实调用时序；新冻结实验达到正确率/FCR/成本标准 | 混用旧 holdout、事后放宽阈值、未授权自动 promotion |
| 待证据 | BUG-09/13d，按 §7.2 限期复核 | 实际并发可达性、确定性影响与正常对照；证据不足时移出活跃清单 | 只有静态窗口、无法闭合共享对象或业务影响 |
| 独立审查 | service_control/web 入口矩阵，见 §8 | 每入口的授权/越权、lease、desired-state 与回执证据 | 未审查区域被误写为漏洞或已安全 |

优先做短、可复现的可靠性验证；不能以“方法库增长”或“schema 较大”为由先开启长期功能实施。真实模型 smoke 使用 GLM-5.3；本次 mock 中的模型名仅为隔离 fixture，不是模型能力测试。

### 7.2 H 级条目的期限与退出规则

BUG-09/13d 建议于 **2026-10-15 23:59（Asia/Shanghai）前完成一次人工复核**，执行人由接手该项者在开工记录中明确。这是本报告建议的复核期限，不代表已安排实验或自动任务。

| 条目 | 升为确证项所需的最小证据 |
|---|---|
| BUG-09 | 真实调用方可同时到达同一实例/缓存；barrier 固定交错；可观察的向量丢失或漏持久化；串行/加锁正常对照 |
| BUG-13d | 真实调用方可并发 load_settings；两个独立 mapping 的 notes 被交叉清除或污染；串行/隔离正常对照 |

到期复核仍无上述证据时，撤回将其作为待修缺陷的主张，移出活跃修复清单，保留编号、H 级历史线索及未验证原因；**不把“未完成验证”改标为“已证明无缺陷”**。如需延长，记录新的具体期限与原因。重新开启必须给出新的可达性证据或触发输入，不能仅重复静态窗口。BUG-16 的上层时限契约也属于待核对事实，但不混入本次两项并发实验。

### 7.3 rev4 补充反例：优先追补的两项开放缺口

以下锚点绑定 **077eca97b30b21af8111385061fd90895e8316f8**，不沿用原基线行号。两项均已在真实模块的隔离导入中复现，未触网。

**BUG-13b 修复回归：显式 mapping 被进程环境覆盖。** config.py:889-895 明确 `load_settings(env)` 从 env_values 装配，但 :1076 改成 `_env_float("LLM_TIMEOUT_S", 120.0)`，遗漏 env_values；`_env_float:152-160` 因 env=None 改读 os.environ。

输入 mapping 含占位 LLM_API_KEY、LLM_BASE_URL=https://audit-fixture.invalid/v1、LLM_MODEL=audit-fixture、隔离 LFL_DATA_DIR 与 LLM_TIMEOUT_S="30"：

| 对照条件 | 起始基线 1ef9652d9 | 修复候选 077eca97b | 契约预期 |
|---|---|---|---|
| 进程环境无 LLM_TIMEOUT_S | 30.0 | **120.0** | mapping 的 30.0 |
| 进程环境 LLM_TIMEOUT_S="93" | 30.0 | **93.0** | mapping 的 30.0 |

追补应把同一 env_values 传入 float parser，保留小数能力。验收必须调用真实 load_settings(env=...)，覆盖 mapping 小数/整数/非法/缺失值、与进程值冲突及 env=None 正常路径；不能只测独立 parser。该结果证明修复引入来源回归，不扩大为所有配置字段均受污染。

**BUG-07 修复缺口：观测未随新的回退参数更新。** providers.py:35-61 的全局观测只在 client_params:352-361 成功发现时写入；后续返回路由时不清除/更新旧值。factory.py:2539-2587 再把该观测与当前 registry 组装在一起。

同一 local/small、LMS_DIRECT=1、registry 路由 http://127.0.0.1:1234/v1 的连续序列：

| 步骤 | client_params 返回 base_url | 随后状态 |
|---|---|---|
| 发现成功，返回 7777 | http://127.0.0.1:7777/v1 | 拨号观测记录 7777 |
| 下一次发现返回 None，回退 registry | **http://127.0.0.1:1234/v1** | llm_base_url=1234，**llm_dial_target 仍为 7777** |

状态查询仍是零发现调用，这项正例保留；失败是“最近一次实际构造参数”与旧观测不一致。追补至少更新每次参数解析的观测生命周期，区分未知/未改写/历史观测，并绑定适用 registry/run 的身份，不能靠测试每例 reset 掩盖旧值。验收覆盖成功→None、成功→异常回退、开关关闭、不同 registry 同标签、状态查询无副作用与无敏感信息。

以上两项未在本轮改行为代码。追补后按相同反例先红后绿，再运行对应配置/路由/状态相邻回归和最终候选门禁；所需部署/live 验收另行绑定实际 release 与 generation。

### 7.3.1 rev5 收口记录（BUG-13b / BUG-07 追补完成）

- **BUG-13b**：`72bcc9236` 修复 load_settings 显式 mapping 的 `LLM_TIMEOUT_S` 来源回归（_env_float 走 env_values，保留小数；覆盖 mapping 小数/整数/非法/缺失、进程值冲突、env=None 路径）。
- **BUG-07**：`bfd902725` 落观测生命周期（成功→None/异常回退、开关关闭、无凭证 URL、rewrite 不可解析均失效旧观测；状态查询零发现零副作用、无敏感信息）；`ec81cb7f1` 补身份绑定：`ProviderRegistry._observation_scope` 实例身份键控观测写入/读取，`dial_target_observation(registry, …)` 按适用 registry 读取，无身份快照返回 None 不泄漏旧式全局键；不同 registry 同标签互不可见/互不覆盖、B 的失效不删 A 的观测、新实例（新 run）不继承旧观测；run latch 的 routing_registry_snapshot 与拨号共用同一 registry 实例，正路径不变（`compare=False` 保持快照相等性语义）。
- **门禁更正**：本报告早前 rev4 对照中的"6686/6688"为局部套件数字，不是全量门禁。真实全量为仓库 `.venv` 下 `python -m pytest tests/ -q`：收口时 **7828 passed / 107 skipped / 16 deselected**（rev4 基线 7823 + 新增 5 个身份验收用例），静态 ruff check 通过。系统 `python3` 缺 pypdf/lark_oapi 依赖，不能作为全量门禁解释器。
- **状态：§7.3 两项缺口 CLOSED（本地门禁口径）**。部署/live 验收仍按上节边界，另行绑定实际 release 与 generation。

## 8. 本次覆盖与边界

rev2 深入复核 session 锁与调用方、provider streaming/error、通用 JSONL 与 Method 检索、Method lifecycle/reflection/status 指标、配置来源与 local client 路由、token budget/breakdown、架构守卫及提交态执行路径，并核对两项后续本地提交。rev3 的新增覆盖限于 §0.3 的当时源码对照、BUG-01/18 隔离复现与独立复核意见追补。rev4 增加七提交 diff、固定候选的 17 文件回归/18 文件 Ruff，以及 §7.3 的基线与当前边界对照；仍未扩大为全项目重新审计。

以下仍没有完整资格结论：

1. `runtime/service_control.py` 与 `web/routes.py` 的认证授权、run lease、desired-state 一致性与全调用链。原报告“已覆盖整个 core/runtime/web”不能代替逐入口审查。
2. 实际 provider 的故障频率、计费、fallback 成功分布及 production 实例 currentness。
3. BUG-09/13d 的确定性并发业务影响；BUG-16 的上层 whole-call/run 时限契约。
4. 原报告代码/测试行数、30 天提交数、worktree 数：本次未复核，且不能用规模替代有效性或覆盖率。

下一次安全审查建议单独建立入口→认证→scope→run lease→执行→回执的矩阵。这是当前最需补齐的审查范围，尚未形成安全性结论。每个实际入口填写完整链路，再检查：

| 审查维度 | 正常对照 | 负例/边界 | 必须绑定的证据 |
|---|---|---|---|
| 认证与 scope | 合法身份、所需 scope、目标 run 匹配 | 缺失/无效身份、scope 不足、跨 run 访问 | 入口、身份来源、授权判断、执行与回执 |
| run lease | 当前持有者的有效 lease | 过期、失效或非持有者操作 | lease 身份、有效期、拒绝时无未授权副作用 |
| desired-state | 目标 generation 与当前实例匹配 | 旧 generation、并发更新、重复控制请求 | desired/observed generation、操作次序、最终状态 |
| 终态与恢复 | 执行结果和控制回执一致 | 取消、部分失败、结果未确认后重试 | run/attempt 身份、副作用、失败/未确认事实 |

以上是待执行的覆盖矩阵，不是本轮发现或复现的漏洞，也不能以正常用例通过替代越权负例。

## 9. 本轮复核回执与可重复条件

**源码权威**：streaming 复现使用固定 release 导入，并将 client.py 文件 SHA256 与 `git show` 内容比较一致：
`97921e15677d28cb530f2ab8578ed204fab25a5a61e6314a42831374d047d75a`。

锁、配置、JSONL、目录优先级与 fallback 分类复现从固定提交 AST 提取真实函数，在隔离 namespace/临时目录中运行；并非完整服务集成测试。streaming 使用 httpx.MockTransport，guard 与 payload 指纹落盘关闭，sleep 替换为立即返回。**provider 网络请求数=0**；表中的“请求2”指 mock handler 调用数。

| 回执 | 内容 | 终态 |
|---|---|---|
| sess-4373-119 | 锁正负对照；配置3项；JSONL；三协议error；Anthropic用量；truncated重试；reasoning-only重试 | exit=0，已观察结果写入相关 BUG |
| sess-4373-130 | 自定义目录同 ID 优先级；GLM 1311/1302/1113 的 429 分类对照 | exit=0 |
| sess-4373-126 | 固定 release cwd 下 Ruff src / src+tests+scripts | 包装脚本exit=0；两笔 Ruff 本身exit=1，诊断30/67 |
| sess-4373-127、133 | 本地提交身份与 MethodStore 变更文件核对 | exit=0 |
| sess-57680-3 | rev3 pin db378621；BUG-01/18/03 函数与原基线、工作树源码对照 | exit=0；仅源码/身份核验 |
| sess-57680-4 | 当前 HEAD 的 BUG-01 真实函数隔离复现，捕获 warning；client/session/config 同源对照、文档链接检查 | exit=0；OSError/ValueError 与日志结果见 §0.3 |
| sess-57680-6 | rev3 HEAD 的 BUG-18 两种目录次序复现；fallback/retriever/search/errors 同源对照 | exit=0；当时来源优先级问题仍存在 |
| sess-57680-9、10、11 | rev4 七提交身份/父子关系、当前文档与 AGENTS、源码/已有测试 diff | exit=0；HEAD/基线见 §0.4 |
| sess-57680-14 | rev4 隔离候选 17 文件首轮回归 | 包装命令 exit=0，pytest exit=1；269 passed/1 必填环境失败 |
| sess-57680-15 | 同候选补齐占位 fixture 后复跑相同 scope | 包装与 pytest 均 exit=0；270 passed/3 warnings |
| sess-57680-17 | 基线/候选 timeout mapping 对照，候选连续拨号参数/状态对照 | exit=0；已观察到 §7.3 两项不符，非表示行为通过 |
| sess-57680-19 | rev4 隔离候选改动 18 文件 Ruff 0.16.5 | exit=0，0 诊断 |

上述 command_id 是本次工具回执定位符，不承诺作为长期机器可读证据源。长期复核应按本文冻结 SHA、输入与预期行为重新执行；后续真正修复须将对应 edge cases 纳入版本化回归测试，绑定最终 candidate 与运行回执。

**重现 BUG-01 的最短用例**（导入必须指向本文固定 release；此示例不改变生产文件）：

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from types import SimpleNamespace
from llm_loop.core.session import SessionStore

with TemporaryDirectory() as tmp:
    owner = SimpleNamespace(
        _dir=Path(tmp) / "sessions",
        _fallback_locks_guard=Lock(),
        _fallback_locks={},
    )
    with SessionStore._shared_file_lock(owner, "audit_lock"):
        raise OSError("body-failure")
# 基线结果：RuntimeError: generator didn't stop after throw()
# 修复后的业务结果应保留原 OSError；不能把“没有异常”当通过。
```

**streaming 重现条件**：client guard_enabled=False、trust_env=False；MockTransport 返回 HTTP 200、content-type=text/event-stream，逐条发送 `data: <JSON>\n\n`。错误序列见 §2；usage 序列见 BUG-11。BUG-12 第一次 response 在 length-only chunk 后抛 httpx.RemoteProtocolError，第二次正常 stop；消费 chat_stream 的所有 delta，并检查 StopIteration.value 的终态 response，不能只用 list(generator) 丢弃返回值。

### 9.1 独立复核与本报告实测：分别记录覆盖

2026-10-08，用户提供了 LFL 对 rev2 的独立审查摘要。该摘要报告了 git 对象/源码抽查，并从原基线 git archive 到隔离目录运行 BUG-01 示例。其独立复验范围与本报告自身的实测范围应分别记录；本次未取得该外部复核的完整机器回执，不将其未复验项包装为第三方重复验证。

| 范围 | LFL 摘要报告的独立核验 | 本报告可主张的证据 |
|---|---|---|
| BUG-01 | 实际运行；RuntimeError、ValueError 对照、业务 OSError 误标锁不可用均一致 | rev2 R；rev3 在当前 HEAD 再次实测，包括日志捕获 |
| BUG-03/04/05/06/11/18；Method list、chars//2 等 | 读码、检索或源码比对；不是这些条目的全套动态复演 | 各条目保持原 R/S 级别；BUG-18 另有 rev3 当前 HEAD 动态对照 |
| BUG-02/12/15 | LFL 明确未独立重跑动态对照 | rev2 的 sess-4373-119/130 已提供本报告实测 R 证据，不因第三方未复验而降级 |
| BUG-17 | LFL 明确未独立重跑，指出环境敏感 | rev2 固定 release/Ruff/cwd/scope 的实测计数；没有当前 HEAD 新计数 |
| “7738 passed” | LFL 未取得独立复验 | 仍为原报告历史摘要，不能升级为本报告实测 |

因此，外部摘要中“未由我复验”的表述只界定该审查者的覆盖，不能理解为 BUG-02/12/15/17 在 rev2 中均未获确证。优先级排序、无 P0 结论和可靠性优先路线获得该复核支持；这不是已修复、已发布或能力收益的新增证明。

## 10. 完成判据

本报告现在可以用于选择和验收窄范围修复，**不能作为全部缺陷已修复、生产已升级或 Method 能力已提升的证明**。

一个条目只有在“固定负例可复现→候选修复→正常与异常回归→最终候选门禁→需要时的 live 验收”证据齐备后才能关闭。能力项还必须满足预注册收益标准；来源不符、未复现和已撤回项不进入已确证缺陷计数。

---

*rev4 保留历史基线与撤回纪律，核对七项本地修复、独立候选回归及 Ruff，追补两项可复现的修复缺口并校正未处理项编号；本次只更新此 Markdown 文档，不构成全部修复、部署或能力收益证明。*
