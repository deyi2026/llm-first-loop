# Changelog（公开变更记录）

> 面向使用者的变更摘要（内部开发过程记录不公开）。版本语义：0.x 内小版本可增补能力，不破坏既有行为。

## Unreleased

- **审批入口补齐执行授权（EVO-20261018-f5f7580a 收尾）**：批量审批支持 `exec_override`（顶层默认、条目可覆盖，非布尔值直接 400 拒绝），accepted 后真正触发执行推进——此前批量路径只置 `accepted`、从不调用执行引擎，档位 0 下永远到不了 `executing`；面板授权勾选框不再只对涉边界条目显示，非边界条目也可逐条显式授权（涉边界条目仍须单条审批 + 安全边界确认）。
- **method 状态转为质量标注（EVO-20261017-lifecycle-alignment）**：知识库除已弃用 `retired` 外全部状态可检索（hold/invalidated/teacher 不再隐藏）；候选卡与 active 同等可用，`record_use` 与评分均为可选；`candidate → active` 一次写入即合法（原 `promotion=pass` 与跨任务类型门禁移除）；排序去掉 lifecycle 权重与零信号衰减，body 权重提高。
- **人工逐条授权不再被执行档位压制（EVO-20261018-f5f7580a）**：`EVOLVE_LOCAL_EXEC=0` 下，人工审批显式勾选 `exec_override` 的演进条目此前永远停在 `accepted`（判定链先命中"仅建议级"，引擎入口更在 level==0 直接 early return，override 根本不被读取），审批通道承诺的自动执行不发生、`evolution_complete` 随之被拒。现改为人工逐条授权优先于全局档位：该授权越过边界/档位/白名单门禁并正常进入 `executing`；`EVOLVE_LOCAL_EXEC` 仍完整约束 AI 自主执行（无授权时 level 0 行为不变），AI 仍不得自授该字段。
- **移除 goal 级知识库 use 硬门（EVO-20261018-f4ca0fc4）**：`create_goal` 的 `method_use_gate`、`task_update` 的 `method_no_contact` 与 Goal 存储字段一并删除。该门默认关闭、从未在生产开启，且自带 `method_no_contact` 免费出口（一条自报声明即可 `→done`），既与不设硬门的规则冲突，也不构成完整性防线；删除不改变运行时默认行为。方法回记收尾提醒（`method_use_reminder`）保留，其专项用例不变。
- **贡献入口对齐**：规则 SoT 按需读取，贡献指南和文档索引不再要求把 playbook 镜像进 universal prompt；中英文 README 的当前版本与评测场景数量对齐权威定义。
- **浏览器测试前置条件如实呈现**：Playwright Chromium 文件缺失时，语义守卫 E2E 按既有可选测试契约标记 skipped，不再因启动不存在的路径产生 setup error。文件缺失和既有 CDP 未就绪分支的 skipped 均表示该环境未验证浏览器能力，不产生浏览器部署资格。
- **Phase4 类型门禁**：分段等待在调用可选打断回调前显式确认其非空；缺失回调时仍继续等待，满足既有保守退化契约和 Pyright 检查。
- **Phase4 保守矩阵测试同步**：确认工具真实进入在途后再入队，以显式事件保持断言窗口并在清理时释放；恢复测试临时修改的 run-generation context。保留原有全部保守矩阵断言，减少入队消费与 run 结束的时序竞争。

## v0.6.32 — 提权闭环安全批次公开披露（2026-10-12）

- **一次性审批令牌 owner-private（commit 523d8b5f6）**：提权审批私有状态文件写入收紧为 owner-only——`O_NOFOLLOW` + 打开后 fstat 校验（regular file、本人 uid、nlink=1），杜绝符号/硬链接替换读取审批令牌的 TOCTOU 窗口；遗留 0644 权限文件读取前在已打开描述符上原地收紧；状态文件损坏从"按空处理"（可被篡改重置审批记录）改为 fail-closed 拒绝覆盖。
- **原子替换消除临时文件暴露（commit c8163f8bf）**：审批状态原子替换的临时文件改为随机名 `O_CREAT|O_EXCL|O_NOFOLLOW` 0600 + fsync + replace，消除 0644 临时文件窗口期内批准令牌对其他本地用户可读的风险，并保持对持久化 registry 的可见性。
- **Web 审批表单拒密码字段（commit 523d8b5f6）**：审批入参 schema 收紧 `extra="forbid"`，审批路径不接受也不回显密码类字段；校验失败时被拦截命令不执行。
- **两层权限边界澄清（docs，commit deff8b620）**：LFL 提权审批只解除灾难性命令安全硬阻断这一道内部门，不等价于操作系统管理员授权——后者由 macOS 原生认证对话框独立把关，二者不可互相替代。
- **质量收尾**：consume 路径 `except ValueError` 补原因注释对齐静默异常吞没守卫（过期时间戳损坏不阻断消费，由工具名/命令哈希强绑定校验兜底）；新增 protected 状态迁移、损坏不可重置、密码字段拒绝、审计日志不含令牌等 16 用例（tests/unit/test_escalation.py）。
- **版本面**：pyproject / web SERVICE_VERSION / README（中英）/ CHANGELOG 对齐 0.6.32；公开库快照自 v0.6.31 增量同步（含 ci-public rule-presence 测试在开源分发环境条件跳过修复，commit 555dd11cc）。

## v0.6.31 — 子代理 E4/E5 原语 + wait 累计预算修复 + chatgpt-web/r9 批次（2026-10-12）

- **E4 子代理 requires 程序级强制白名单（EVO-20261012-bb3022f4，commit 842c24309）**：`spawn_subagent` 的 `requires.tools` 从元数据声明升级为程序级强制——子会话工具发现面与执行面均截断到声明集；声明超出父执行域在启动前确定性拒绝（授权只降不升，fail-fast）；默认从子代理工具面剔除 spawn_subagent 防递归舰队（`CHILD_SPAWN_GRANT` 配置白名单显式授予）；成功回执携带 `tool_scope` 透明化实际生效白名单。此前 V2a POC 实测证伪了“requires 仅声明”假设（bf3566b45）。
- **E5 子代理 wait 只读等待原语（EVO-20261012-65475c5a，commit 842c24309）**：1..120s 确定性阻塞，等待期零模型调用；父会话取消 ≤0.5s 唤醒；每子会话累计 ≤600s 预算。心跳/轮询等待期以它替代多轮空转（Mode-L 空闲成本 ~64-96K in/min 降频 4-10 倍）。验证：单测 7462 passed + 专项 12 项。
- **E5 累计预算跨 registry 派发快照丢失修复（EVO-20261012-32e89b46，commit 3d5a6eb94）**：`child_wait_budget_used` 从 ContextVar 值语义改为共享可变载体 WaitBudget（与 child_cancel_event 同模式）——registry 每次工具派发 `copy_context()` 拍快照，值 set 写入副本即弃，live 实测连续 wait 回执累计恒为单次值、600s 累计上限形同虚设。修复后预算随派发边界原子传递，并新增经 `registry.execute` 真实派发路径的回归测试（直调单测测不出 copy_context 边界——上轮 E2E 暴露的系统性盲区）。已随全舰队（web/feishu/learning）重启部署验证。
- **chatgpt-web 稳定性批次（10-11）**：会话段内稳定前缀变化告警（d3518d8ab）；发送确认时展开折叠长回合（2059e84d4）；字面 lfl-model-response 围栏作纯文本回退收割（8128e71dc）；运行时关闭的自有标签页自愈不重启（2b7e932d0）；surface 租约恢复对损坏与额外上下文加固（35da887ea）；surface 未连接时 fail-closed 抛租赁错误（42886bb30）。
- **离线双代理保证门默认关（0b8cfa370）**：offline dual-agent gate 集成进主链路，默认关闭。
- **r9 守卫与门禁批次（10-11）**：静默异常吞没守卫——except+单条 pass 必须带原因说明（a48094102/f5799c467/0d2574d66）；诊断棘轮不再把缓存不可写误报为 runner crashed（4f12265cc）；ci_gate 管道早关导致的门禁基建失败修复并清零 ruff BLOCK NEW（9ac1740e5）。
- **版本面**：pyproject / web SERVICE_VERSION / README（中英）/ CHANGELOG 全表面对齐 0.6.31（版本一致性测试约束）。
- **公开库 CI 适配（2026-10-12 追记）**：rule-presence 账本契约测试在无内部治理目录（`.codeartsdoer`）的开源分发环境条件跳过（对齐 test_docs_sync 既有口径）——首轮公开库快照 CI 因该目录不随库分发而 FileNotFoundError 误报失败。
- **提权闭环安全批次（10-12 追记，523d8b5f6/73e09586d/c8163f8bf/deff8b620，尚未进公开快照）**：EscalationStore 状态/审计/锁文件全面 owner-only 0600——`O_NOFOLLOW` 打开 + fstat 校验（regular/本人 uid/nlink=1，防符号链接与硬链接替换），遗留 0644 文件在打开的描述符上读前收紧；状态损坏从 fail-open"按空处理"改为 fail-closed 拒绝覆盖（防篡改重置审批记录）；审批令牌不写入审计日志；新状态以随机名 `O_CREAT|O_EXCL|O_NOFOLLOW` 0600 创建 + fsync + 原子 replace（消除 0644 临时文件暴露批准令牌的窗口，且对 durability 写扫描器可见）；Web 审批请求 schema `extra="forbid"` 拒绝一切未声明字段（含管理员密码——Web 审批是任务决定而非 OS 密码收集 API，字段被拒后被拦命令不执行）。设计文档明确 LFL 审批与 macOS 原生管理员授权两层不可互代。已随全舰队部署（web gen239 / feishu / learning，git a691955f1）。

## v0.6.30 — 经验使用声明账本化 + 知识库 use 硬门双源（2026-10-11）

- **经验使用声明落账（EVO-20261011-945fc53c 方案A+B）**：`refine_experience(action=record_use)` 从"只回执不落账"升级为真值源账本 `experiences/usage.jsonl`——与 method 侧同构的跨进程 flock + fsync + 单调水位（`.usage_watermark.json`），追加失败如实 FAILURE（fail-closed，不降级）；新增 `ExperienceStore.record_use/usage_entries/check_usage_integrity`；`knowledge_runtime` 事件流降级为观察通道。一次性迁移脚本 `scripts/migrate_experience_usage_ledger.py` 回放历史 6 条声明（含 2026-10-10 的 4 条），幂等键 `knowledge_event_key` 可安全重跑。
- **知识库 use 硬门双源（EVO-20261011-d6b04567 方案C）**：`method_use_gate` 通过路径扩展为 method/experience 双源（各自 usage.jsonl 按 session_id 归属）；`task_update(method_no_contact=...)` 语义澄清为知识库级（方法库与经验库均未接触），描述与 goal 提示同步；审计兼容注明：2026-10-11 前历史 `false` 只表示"未显式声明无方法库接触"，不蕴含经验库证据。方案权衡（D）：不做 record_use 账本化与门禁硬绑定（保持方法/经验两层独立）。
- **补记（同日早间提交，初版条目未列）**：runner SSE GC 清理允许重入 registry guard（75bb2b5c3，2026-10-11）。

## v0.6.29 — 浏览器精确寻址 + 中文经验落盘修复 + web_search 词典降级标注（2026-10-10）

- **浏览器目标精确寻址三选一（EVO-20261010-1e06d6b4，commit ab4fd70a5）**：`browser_operate` 目标寻址三种形态——raw name 字节精确（kind+name）、确定性归一键（kind+name_normalized，零宽剥离/空白折叠）、grounding_ref 复用（受 world-version retention 约束）；混合形态或空值确定性拒绝。身份未命中回执有界候选清单替代旧 fuzzy 重绑，杜绝最新匹配静默漂移。
- **经验落盘中文标题修复（commit 9e8f3abd9）**：`sanitize_slug` 改用 Unicode 感知 `\w`，中文标题经验不再塌缩为同日 `untitled` 冲突导致拒写；空 slug 兜底改 `untitled-{title_sha256 前 8 位}`，纯符号标题互不冲突；ASCII 旧 slug 行为不变。同日同 slug 仍拒绝写入（重试幂等契约不变）。上线当晚真实样本验证：同日两条不同中文标题经验均落盘，与修复前遗留的同日 `untitled` 文件共存无冲突。
- **web_search 词典降级检测与回执标注（EVO-20261010-528ab2f3，commit 692aef752）**：bing general 通道对孤立普通词（如 production/端/具）返回词典站结果（剑桥词典/iciba/百度百科词条页）时，回执标注 `[词典降级] degraded_backend=bing_dictionary_fallback` 与改写建议；header 与结果行原样保留（不改变返回结构）。query 含词条意图标记（意思/翻译/发音/definition of 等）时豁免不标注。
- **版本面**：pyproject / web `SERVICE_VERSION` / README（中英）/ CHANGELOG 全表面对齐 0.6.29（版本一致性测试约束）。

## v0.6.28 — 插件与能力生态接入 + 导出 MCP server + R9 规则内化与预算治理（2026-10-10）

- **只读导出 MCP server（`llm_loop export-serve-mcp`）**：把经验库、方法库、证据 ledger、能力目录以 MCP 协议（stdio，newline-delimited JSON-RPC）导出，供外部 Agent 宿主（Claude Desktop 等任意 MCP 客户端）直接复用 LFL 差异化能力；legacy `initialize` 握手（echo 客户端协议版本，支持 2024-11-05 / 2025-03-26 / 2025-06-18）。
- **工具面（7 个，全部只读）**：`search_experience` / `read_experience`、`search_method` / `read_method`、`list_capabilities`；证据面 `search_evidence` / `read_evidence` 显式 opt-in（`LFL_EXPORT_EVIDENCE_OWNER=workspace_id/session_id` 或 `--evidence-owner`）——证据按 owner scope 隔离，外部消费者默认不持有任何 scope，故默认禁用。
- **硬只读边界**：所有 store 以恒拒写 `write_guard` 构造，无写路径；不装配对话 engine、不执行模型调用、无 LLM 凭证依赖（Settings 不可用时回落纯文件默认路径）。
- **入口**：`llm_loop export-serve-mcp [--experiences-dir … --methods-dir … --evidence-owner …]`，或 `python -m llm_loop.export.mcp_server`。
- **插件与能力生态接入（P1/P2，`DESIGN-20261009-plugin-ecosystem-integration`）**：标准包层（formats/store/catalog + skills 标准解析）；MCP 协议/传输分层（stdio/HTTP 双传输、游标分页、断线运行恢复、`connection_epoch` 代际、FR-05 OAuth）；多源配置合并优先级 + 精确身份冲突报告 + 装配 epoch；外部生态配置适配器（Claude / Codex / Gemini / Cursor / VS Code 五家，只读导入零重写）；resources/prompts capability routing + legacy SSE 传输 + git/archive 安装源 + MCP registry 发现。
- **R9 规则内化**：SOUL.MD 人格宪章与 RULE-AI-01 真话断言（SoT 指针）固定在系统前缀头，规则文件改坏时 fail-closed。
- **Web 预算治理（TaskBudget I5 系列）**：签名 Web TaskBudget canary（admin one-run CAS 切换）、预算 Provider 尝试隔离在可杀 worker、Stop 关闭预算 SSE socket 并保留 UNKNOWN、多路复用预算 SSE fail-closed、操作员人工 ACL 与一次性签发、restart 管道加固、Web 预算准入尊重 API Bearer 认证。
- **知识消费**：知识消费回执接入主代、有界 Web 知识消费额度、scoped session digests + freeze 消费试点。
- **学习方法面**：method activation 跨任务类型门（EVO-20261010-994e30f4）；append-only usage ledger 防 git 树回退；委托子代理任务模板内嵌 method discovery 纪律行。
- **静态质量棘轮**：pyright/ruff 新增欠债清零（冻结 ledger 45→32）；static ratchet 回执自证环境指纹（per-source provenance）；deployed-env 泄漏测试隔离批次；import-exempt 登记簿。
- **Skills**：学术研究 skill 第 1/2 梯队（7 个：arXiv 全文检索、引文核验、citation-graph 追溯等）。
- **文档**：Python ≥3.13 首屏支持策略声明；消费率/收益度量预注册 v1；外部生态横向对比评审。
- **版本面**：pyproject / web `SERVICE_VERSION` / README（中英）/ CHANGELOG 全表面对齐 0.6.28（版本一致性测试约束）。

## v0.6.27 — 多查询融合影子模式 + 浏览器感知/操作 + 服务生命周期控制（2026-10-08）

- **多查询融合影子模式（默认 off，零行为变化）**：`RETRIEVAL_MULTIQUERY_MODE=shadow` 启用后，生产 memory 语义检索旁路执行"原查询 + LLM 盲改写 2 变体"的等权 RRF 融合，只记录不生效；返回值与 off 逐字节一致（单测锁定）。目的：接入评审前实测改写延迟、检索成本与 top1 置换率。
- **观测契约**：`<data_dir>/retrieval_shadow.jsonl` 每查询一条（latency 分解/primary vs fused top10/overlap@5/primary top1 保位标志）；探针全异常捕获，LLM 失败/落盘失败只记 error 行，绝不影响主路径。
- **防递归**：变体检索经 `_skip_shadow` 复用 `_search_memory`；enforce 路径明确不做，待影子数据过决策门（docs/DESIGN-20260924-multiquery-fusion-shadow.md）。
- **浏览器感知/操作双工具（CDP 接管真实 Chromium）**：`browser_perceive` 只读感知（snapshot 语义对象投影 + 固定参数视觉证据截图、hydrate 精确 ref、diff、wait——页面就绪/URL/对象状态/文本）与 `browser_operate` 单派发 mutation（navigate/click/set_text/append_text/select/scroll）；操作目标 = 精确 kind+name grounding + 版本化，程序不做 fuzzy/重试/完成判断。
- **多标签页显式换绑（EVO-20261007-11ae668f）**：页面清单回执 page_id；携带 target_id 的调用是独立动作（两 host 原子换绑），观察/操作在后续不带 target_id 的调用发起；语义对象投影支持 kind 过滤 + 游标分页（EVO-20260918-c69527a1）。
- **浏览器 attestation**：argv 原生 NUL 源修复；M3 语义守卫 E2E（真实 Chromium 全链路）跑通并修复配套缺陷。
- **服务生命周期控制（service_control）**：restart/update 默认分离 worker 后台执行（`--wait` 内联等待）；grant_lost_owner_dead 确定性降级；发布固定 release checkout（双根 sidecar .env 兼容独立 venv）。
- **调度持久化修复**：混合版本写者下一次性 wake 权限保持；到期认领前恢复委托 owner；实际 run 准入时恢复一次性 wake。
- **Web 认证与会话**：308 规范化源回跳、v2 会话 cookie（host-only、父域配置修复）、回环豁免收紧、ProxyHeaders 下 308 修复；移动端登录/剪贴板修复；interject 孤儿恢复；KaTeX 懒加载。
- **检索与学习**：语义检索 rollout 稳定化与服务级语义运行时配置；反思期语义 method 检索；method 生命周期闭环 v2.2（record_use / record_qualification / annotate_freshness / 状态流转）；method discovery 衰减零信号候选。
- **验证器**：第三方评述豁免 + 跨语言动词↔工具名回执匹配。
- **诚实口径**：honesty_rate 统计口径修复（防重复计入）。
- **LLM 引擎事实面**：settled response facts、attempt ids、传输尝试 prepared facts、keyed HMAC 摘要、重复 tool fingerprint 规范化。
- **演进通道**：人工 exec_override 授权通道（RULE-AI-26，EVO-20260929 方案A）。
- **ChatGPT Web 浏览器托管 provider 稳定性**：绑定生命周期可观测与告警、浏览器内模型切换、线程绑定 IO、瞬态导航身份容忍、配置收敛到 Web 域。
- **版本面**：pyproject / web SERVICE_VERSION / README（中英）/ CHANGELOG 全表面对齐 0.6.27（版本一致性测试约束）；内部治理审计类文档不再随公开库分发。

## v0.6.26 — 语义缓存冷启动批量预热 + 持久化去抖（2026-09-24）

- **冷启动静默降质修复（EVO-20260924-d9c5ad20）**：语料增长后首批查询在 `timeout_s=1.0` 下超时 → 静默回退 keyword（评测实测 h@5 14 抖到 9~12，生产同样存在该窗口）。根因：`_embed_cached` 逐条惰性嵌入且每条 persist 整个缓存 JSON（N 条新文档 = N 次 ~2MB 重写）。
- **embed_batch 协议（可选方法）**：APIEmbedder 单请求 64/片，响应不齐/异常整批回退逐条；Hash/Null 逐条语义；旧实现 getattr 探测兼容。
- **search 内预算预热**：语义召回前增量预热未缓存候选，每片前查 deadline、超时停片，不挂预算外时间。
- **持久化去抖**：每缓存每查询 persist ≤1 次（try/finally 含超时降级路径，已嵌向量不丢）。
- **顺手修复**：_cache_route 消重 kind 路由；method 缓存 setdefault 真缓存（原临时 dict 丢失）；regression_gate check_regression 结构 bug（overall/by_kind 层级混用下标必崩、比较路径从未生效），基线按语料 1761 快照刷新。
- **GLM overflow 识别补充**（6a1de842c）：is_overflow_error 新增 GLM 400 code 1261 码路径（限 glm/glm-api/zhipu provider），文案本地化识别保留。
- **验收**：冷启动端到端（仅 index 无向量缓存，corpus 1761）单查询最大 1.27s、4 条查询窗口后恢复 mixed/semantic、缓存全建；旧代码同场景对照 + regression_gate PASS。
- **资产入库**：retrieval 多查询融合原型与融合权重消融（等权 RRF 保留结论）、3 条 method 卡、1 条 held-out 阴性结果 lesson。

## v0.6.25 — restart 三件套修复链 + 端口口径清扫 + convergence 快照 + 版本面对齐（2026-09-24）

- **restart 互斥锁路径修复**：v0.6.24 引入的互斥锁引用 `$DATA_DIR`，该键在 restart_system.sh 中是被 unset 的危险键——set -u 下 unbound → 脚本秒退（rc=1）→ 早退路径不写回执 → 陈旧回执误报 action_id_mismatch（13:4x 两连 restart 失败实证）。锁路径改锚 `MIRROR_DIR/data/runtime`，与 _write_receipt 同一事实源。
- **restart 三件套（gen105 实战验证通过）**：① 陈旧回执误判——回执 ts 早于本次 action 创建 → stale_receipt + 脚本输出尾部透传（陈旧≠零副作用证明，仍 fail-closed keep）；② _stop_service argv 双面探针（runtime.launch 新面 + 旧面，PROJECT_DIR 锚定）+ web 端口权威兜底（PID 校验含 PROJECT_DIR 防误杀），等待/强杀按 PID+端口释放，弃 pkill -f；③ _start_service 撞端口幂等——本项目占用者优雅停后重启，非本项目占用者如实拒绝。
- **端口口径清扫（8902 残留归零）**：guard 健康判定端口清单从镜像 .env 读权威 WEB_PORT（默认 8903）起扫；restart_system WEB_PORT 默认链 env > .env > 8903；web/__init__.py 默认端口 8902→8903、service_control 判活回退区间 8902-8905→8903-8905。78 处注释同步改为"旧主区"口径。
- **service_control convergence 快照**：publish/update 成功回执附只读 lagging 列表（compose_convergence_view 纯派生 identity view），调用方可见其它服务代差（此前 feishu 滞后 gen98→103 无人重启直到告警）；不新增门禁/锁/restart action。
- **knowledge-health advisory**：method store untracked 积压超阈值（>50 文件）时 warnings 置 `method_store_untracked_backlog`——只告警，不隔离、不封写。
- **知识/资产入库**：docs 10 篇（hev0-p3 三臂运行时设计与结论、retrieval-AB 与 miss 归因修正报告、authority-map 拒收审计等）；method store 154 条与 experiences 25 条积压入库；evals/retrieval_ab 评测脚本与结果基线；tunnel-watchdog 与 fuyao 数据客户端。
- **版本面对齐修复**：v0.6.24 发布漏更 `routes.SERVICE_VERSION`（停在 0.6.23）与 README.en.md（停在 0.6.23），`test_public_version_surfaces_match_project_version` 红——本次全表面对齐 0.6.25，一致性测试恢复绿。

## v0.6.24 — restart 双通道互斥锁 + web 判活端口兜底（2026-09-24）

- **背景（13:08 双通道并发实证）**：权威通道（service_control→restart_mirror.sh）停旧进程的端口空窗恰被 guard 巡检命中 detect_fail → restart_system.sh 并发拉起 → 双 web 抢 8903 一活（29418）一死（29502），死进程退出前写的 runtime_manifest.web.json 留下死 pid → 面板/status 误报 live_pid_not_running（"重启没生效"假象）；guard 随后 pull_up_ok 探测到的其实是活通道的进程。
- **互斥锁（源头）**：restart_mirror.sh（web/feishu/all 分支 preflight 后）与 restart_system.sh（两处 restart 分支）执行段持有 `data/runtime/restart-in-progress.lock`（写 ts+pid+argv，trap EXIT 清理）；guard_system.sh `_ensure_service` 在 pull_up 前检查锁新鲜（<120s，BSD stat -f %m）→ 跳过本轮（skip_pull_up 日志），下轮巡检自然复核。锁语义防并发不防重入——guard 自己经 restart_system.sh restart 持锁不受影响。
- **端口兜底（观察面）**：`compose_service_identity_view` web 判活升级——manifest pid 死且端口（8902-8905，guard v0.6.20 同口径）有 llm_loop 监听者时，以端口监听者为准（`pid_source=port_listener`，manifest 原值降级 `manifest_pid` 保留展示），对齐"单一权威探针=端口"原则；无监听者（真死）维持如实误报不掩盖。manifest last-writer 可被短命写者污染，端口不会被污染。
- **测试**：端口兜底 2 例（死 pid+活端口→替换且 restart_required 消除 / 无端口→维持 live_pid_not_running）；三脚本 bash -n 通过；关联面 106 passed。

## v0.6.23 — Learning 面板全历史口径 + reflection 防重复门（2026-09-24）

- **counts 全历史口径（面板"已生成"不再倒数）**：`/learning/status` 的 counts 原在 `recent_jobs(limit)` 窗口内按 state 统计——saved job 滚出窗口（新任务持续进来）时"已生成"回退，用户误以为方法卡被删（方法卡实际持久保存于 `data/methods/`）。现改为 `LearningJournal.count_states()`：terminal 态（saved/none/failed/cancelled）全折单调累计，in-flight 态即当前在飞；`count_states` 异常 fail-open 回退窗口口径（observability 永不阻断服务）。
- **reflection 防重复门（语义重复短路，止 token 浪费）**：反思 payload 新增 `existing_methods`——方法池 active/qualified 卡一行摘要（id + description 截断 110 字符，上限 30 条，约 1-2k token）；system 指令增加 dup 短路：拟蒸馏方法与任一清单条目语义重复（同触发/同机制，措辞改写）时 `decision=none, reason=dup:<method_id>`，不再铸造仅哈希不同、语义冗余的新卡。此前字节级幂等只挡住完全同 body 的重复，近义改写会绕过（重复触发反思 LLM 调用 + 产出重复卡，双份 token 浪费）。清单构造 fail-open：store 异常时空清单，反思照常。
- **版本一致性修复**：`routes.SERVICE_VERSION` 停在 0.6.15（自 T7 后未随发布同步），`test_public_version_surfaces_match_project_version` 因此红——本次随三件套对齐至 0.6.23（CHANGELOG + pyproject + tag 同次提交）。
- **测试**：`test_learning_counts_and_dedup.py` 5 例（saved 出窗口仍计入 / queued+none 同折 / status 全历史口径 / existing_methods 仅 active+qualified / store 异常 fail-open）；全量 unit 5953 passed, 107 skipped。

## v0.6.22（补发点）— release 动作补齐：pyproject bump + v0.6.22 tag（2026-09-24）

- **背景（web 横幅版本恒显示 v0.6.15-dev.N 根因）**：CHANGELOG 自 v0.6.16（09-24）起连续 7 个版本只写条目不发布——`pyproject.toml` 版本停在 0.6.15、git release tag 停在 v0.6.14（距 HEAD 253 提交）。`build_identity.display` 语义为 `{pyproject 版本}-dev.{距最近 v* tag 提交数}+g{短hash}`，机制正常工作，缺的是发布动作本身。
- **补发**：pyproject `0.6.15 → 0.6.22` + 打 tag `v0.6.22`（HEAD 5d90e8590，含 v0.6.16~v0.6.22 全部条目；历史版本不追溯补 tag——tag 语义是发布点，v0.6.22 为首个补发点）。发布后 `display = v0.6.22`（release_exact：HEAD 带 v0.6.22 tag 且树干净）。
- **今后纪律**：CHANGELOG 新增版本条目时同步三件套——CHANGELOG 条目 + pyproject bump + `git tag v<version>`；缺任一项视为未发布（display 将继续显示 -dev 后缀，属如实暴露而非 bug）。

## v0.6.22 — 后台动作失败终态的轮级注入（EVO-20260924-62221fd4，2026-09-24）

- **背景（异步拒绝可见性缺口）**：受理时拒绝（admission barrier）同步返回调用会话，模型即时可见；执行时拒绝/终止（fail-fast、绑定失效）发生在调用会话结束之后——v0.6.19 保证 failed 单不丢失（保留待 verify_acknowledge），v0.6.20 保证人侧可见（guard 推送），但模型侧只有"下次碰巧查 status"。gap 与 E13（web 换端口无人知）同构，对象从人换成模型。
- **轮级注入**：engine 每个 human turn 在用户原文之前检查未确认 failed 动作的**增量**（`build_failed_action_turn_notice`）：复用"程序附录·非用户输入"STATUS 通道，每卡 ≤3 条、每条一行（detail 截 120 字）；幂等——同一 action_id 本会话只注入一次（开场卡与轮卡共用 `metadata.service_action_ids` 去重登记）；闭合即停（acknowledge 后扫描不再返回，无需撤销）；提示非指令——被注入不等于必须 verify_acknowledge，语义保持"待确认待消费"；fail-open。
- **验证门槛（弱模型档行为对照）**：qwen3.8-flash-next（cognilocal 8901，temperature=0）A/B 臂各测身份轮（"你是什么大模型"）+任务轮（水果补全）：A/B 回答逐字一致（身份正确自称 Qwen、无 DeepSeek 误称；任务均正确完成）——轮卡注入零行为劣化（对照 2026-09-24 早前方法池卡注入把弱模型身份带偏自称 DeepSeek-V4 的事故，STATUS 层短卡干净通过）。
- **测试**：`test_evo_62221fd4_turn_notice.py` 5 例（过滤+上限/STATUS 层渲染/轮级接线与用户原文尾位/幂等/闭合即停）；全量 unit 5948 passed, 107 skipped。

## v0.6.21 — runtime_manifest service-specific 身份活进程守卫（面板误报修复，2026-09-24）

- **背景（面板误报 live_pid_not_running 实证）**：gen93 三单 restart 均 succeeded 后，面板/status 报 web `restart_required: live_pid_not_running`（pid 90928 不存在），而真实 web（pid 90846）正监听 8903 并正常服务。根因：restart 探测路径上的一个短命进程（11:32:19 写入，约 5s 后退出）在真实 web 之后执行了 web 启动路径并**覆盖** `runtime_manifest.web.json` 的 pid——specific 身份文件是单写者无锁 last-writer 语义，短命进程天然胜出。
- **守卫语义**：`write_manifest` 写 service-specific 文件前检查既有持有者——旧 pid 存活且 argv 属 llm_loop 进程族 → 本次（通常是短命的）写入者不覆盖，仅写 merged 兼容文件并 log。旧持有者已死/无法核实（ps 异常 fail-open）→ 保持历史 last-writer 语义正常覆盖，真实重启路径不受影响。标记放宽为进程族匹配（探测/启动路径子进程 argv 不稳定含服务模块名，pytest 会话即反例）；pid 复用给非 llm_loop 进程时必然放行；误跳过的恢复出口为删除 specific 文件后重启（人工可处置低频边界）。
- **测试**：`test_runtime_manifest_live_guard.py` 4 例（活持有者不覆盖 / 死持有者放行 / 非 llm_loop 复用放行 / ps 异常 fail-open）；全量 unit 5943 passed, 107 skipped。生效需服务重启载入（守卫在 manifest 写入路径上）。

## v0.6.20 — guard 常驻守护恢复：健康判定对齐新部署面 + 主动告知（2026-09-24）

- **背景（web 死亡/换端口无人知复盘）**：guard launchd 守护自 2026-08-27 起处于 disabled 状态且已失效——①plist 仍指向迁移前旧目录（`llm-first-loop`，127 command not found）；②`restart_system.sh`/`restart_mirror.sh` 丢失执行权限（pull_up 恒 Permission denied）；③健康判定只见旧面（web.pid + `llm_loop.web` 进程 + 固定 8902），对 service_control desired-state 起的 `llm_loop.runtime.launch web` 新面进程永远误报不健康（实例：pid 14036@8903 正常服务中仍被 detect_fail）。
- **健康判定对齐（guard 职责收敛）**：`_service_healthy` 先按新面进程存活（ps+grep 行尾锚定；BSD pgrep -f 的 `$` 锚实测不可靠弃用）+ web 端口探测（8902-8905 任一 `/health` 应答 200/401 即听）判定；进程级死亡/端口级失听才拉起兜底；feishu/learning 以进程存活为底线——半僵/部署一致性归 service_control 面（verify_acknowledge），guard 不越权判定。
- **主动告知通道**：detect_fail/拉起失败/恢复 即推 macOS 本地通知（`_notify_guard`，`GUARD_NOTIFY=0` 可关）——异常不再只写 guard.log 等人来查。
- **恢复部署**：plist 路径改 mirror 目录、执行权限修复（mode change）、launchd bootstrap 重载（KeepAlive 常驻，守护死亡自动拉起）；实测 once 与常驻循环对活服务零误报。

## v0.6.19 — service_control 终态反馈闭环三断点（EVO-20260924-8266b693）（2026-09-24）

- **终态事件入统一事件流（A）**：`runtime/service_control` 新增 `_emit_terminal_event`——restart/publish 动作落终态（succeeded/failed）时同步写 `service_action_terminal` 事件（action_id/target/generation/status/detail/verify_verdict），event_stream 查 action_id 不再只见模型自身 action_trace。2026-09-24 09:46 restart failed（git_head mismatch，只落私有台账）即此类断点实例。
- **开场状态提醒 + 待确认语义（B）**：pending_actions 投影与引擎共享单源扫描 `scan_unacknowledged_failed_actions`（runtime/service_control 导出）：failed 且 `acknowledged_at` 为空持续占用投影；desired 代已前进（被接管）不再从投影抹除——标注 `superseded=True` 保留痕迹，"接管即抹除"失效，唯一清除出口是 `verify_acknowledge(verdict=accept)`（写 `acknowledged_at`，物理状态保持 failed 不篡改）。会话开场（首个 genuine human turn）注入一次 STATUS 层非祈使提醒（`engine_services/service_action_notice.py`：≤10 条单行、无正文投喂、位于用户原文之前满足尾位不变量、fail-open、每 session 一次）；注入点必须在用户消息落库**之前**——首版误置于落库后导致首 turn 恒不触发，已修正并回归。
- **受理回执收口（C）**：`service_control` 工具受理回执明确"受理≠完成"语义 + 终态核对入口（`status` / event_stream `service_action_terminal` / `verify_acknowledge`），收窄"受理回执被误读为已完成"的空间（今晨 08:26 '还没有重启'断点）。
- **验证**：定向 21 passed（新测试 `test_evo_8266b693_service_action_feedback.py` 覆盖 A/B/C 三面 + 引擎开场注入顺序/一次性/尾位）；全量 unit 回归 5939 passed, 107 skipped（venv，退出码 0）。

## v0.6.18 — 故障台账边界外延五项（EVO-20260924-40755734）（2026-09-24）

- **前置拦截入账（A-①）**：registry 执行前拒绝路径全部接入故障台账——新增 `_preblock` 包裹（call_id 缺失/工具隔离/预检路由/提权令牌无效/安全硬阻断/共享服务拦截/EXEC_MODE 权限拦截 8 处）+ `_result` 收口挂 notify（工具不存在/参数校验/预检失败/物化失败/单调守卫 5 处）。今晨 `service_control` 参数名连错两次即此类（此前观察者收口点之前 return 绕过台账）；新增测试含"真实安全硬阻断 BLOCKED 全链路入账"。
- **python 指纹词级形态（A-②）**：已随 v0.6.17 落地（`_PY_WORD_RE` 词级匹配覆盖 `cd X && python3 …`），本版补录建议项归属，无代码变化。
- **pytest 汇总行修复（A-③）**：根因确证为 `addopts` 内嵌 `-q` 与调用方显式 `-q` 叠加成 `-qq`（隐藏最终 `N passed` 汇总行，验证只能靠退出码）；非 pytest 9.1 bug、非 conftest 插件（隔离目录对照 + 不传 -q 对照 + 注释 audit print 对照三重实验定位）。修复：addopts 移除内嵌 `-q`（所有脚本调用方均显式携带 -q，零行为破坏），修复后单层 -q 汇总行恢复可见。
- **同形态故障自动提醒（A-④）**：`record_tool_fault` 增签名计数，同 (phase, error_type) 达阈值 3 时记 `tool_fault_repeat` 台账条目（含计数与样本）+ `report_event` 走既有冷却事件通道（每签名一次）；不新增 prompt 注入路径。
- **`faults` 聚合入口（A-⑤）**：CLI 新子命令 `llm_loop faults [--limit N] [--data-dir DIR]`——只读 exception_log.jsonl，按签名聚合 top + 最近明细；实测 5 条样例（含 repeat 条目）输出正确。

## v0.6.17 — 工具故障可追溯最小闭环（2026-09-24）

- **工具回执故障台账**：所有工具真实执行收口点（正常/ BLOCKED post-hook / 异常三处）统一通知 `post_result_observer`（registry 新 API `add_post_result_observer`，与 pre-hook 对称，观察者 fail-open）；factory 装配观察者将非 SUCCESS 回执（failure/timeout/error/blocked/unauthorized）与 execute_command "成功但零输出"哨兵写入 `exception_log.jsonl`（status 新增 `record_tool_fault`，与 record_exception 同构，`search_records(kind=exception_log)` 既有检索路径零改动可查）。解决"出错无记录、模型不知道错在哪"：今早实测 5 类事故（done+0 行输出、pytest 汇总行被吞、python3 漂移 homebrew 3.14、参数协议错、重启计划中断）此前全部无台账。
- **python 解释器指纹**：词级含 python/python3 的故障命令（非零退出码或 runtime_fact 存在时）回执附 `[py] python3=<path> | python=<path>`，覆盖 `cd X && python3 …` 非裸形态（`_workspace_python_env` 只 pin 裸命令，今早 pypdf 16 收集错误即此漏网形态）；纯成功回执不附（保住"成功=纯 stdout"契约，scrubs_env 既有断言零改动通过）。
- **job_output 终态零输出提示**：后台任务 completed/failed 但本进程 0 行输出时附 `[空输出提示]`（管道 tail/swallow 形态如实标注，提示以落盘文件交叉验证，不判定产出）。
- **边界**：前置拦截（安全阻断/参数校验/工具不存在）不经过 observer（本期范围外）；台账只记故障形态，正常流不记。单测 `test_tool_fault_ledger.py` 6 项（落盘/fail-open/通知语义/指纹词级匹配与纯成功不附/终态零输出提示），关联面 47 passed、全量 unit 回归绿。

## v0.6.16 — update_goal 终局证据硬门（EVO-20260923-6bcc4880）（2026-09-24）

- **终局证据门**：`update_goal(status=complete)` 从"自由文本 reason 即可收口"升级为程序级强制：① 任务图存在 open 任务拒绝（既有语义保留）；② `evidence_required` 任务 `evidence_verification_status != verified` → BLOCKED `evidence_unverified`（防账本存量/篡改数据无凭收口；任务写入轴的 verifier 强制使该路径成为纵深防御）；③ 无 done 任务依托（空任务图/全非 done）→ 需自报 `evidence_refs` 并过 `TaskEvidenceVerifier` 真实性校验，否则 BLOCKED `no_finality_evidence` / `evidence_below_threshold`；④ 任务账本不可读 → BLOCKED `probe_unavailable` fail-closed（不写终局而非照写——终局书写路径上的 fail-open 语义修正，普通路径 fail-open 不变）。`blocked` 是异常出口不走门；schema 新增可选 `evidence_refs` 参数；goal 记录损坏/不存在仍优先如实报告（证据门不掩盖存储诊断）。拒绝形态对齐拒收纪律：BLOCKED + `reason_code` + 出口指路（补证据/建任务图/人工 waive），拒绝的是书写不是记录（ToolResult 照常入历史与事件流）。等级→书写权的 E1/E2/E3 分档映射仍留人工定档，本版只立门（与 evolution 建议原文一致）。

## v0.6.15 — Restart admission gap ②: learning idle gate and dependency-scoped task registry（2026-09-20）

- **learning 空闲门**：`service_control` restart 对 `learning`/`all` 目标新增 busy 探测（此前 `learning has no busy gate`，与 `restart_mirror.sh` 一致地无门）。探测为 durable 事实组合（新模块 `runtime/learning_idle.py`）：`data/sessions/learning/consumer.lock`（flock）判定专属 learning 进程是否存活 + journal fold 的 `admitted`/`started` 判定是否有任务在飞。busy 仅当"持锁且有在飞"；进程死亡时残留 `started` 是崩溃现场而非在飞（post-crash reconcile 重跑），不构成 busy——否则重启 learning 一次之后的第二次重启将永远等不到 idle。锁路径常量单源化：`learning_runtime` 与探测共用 `consumer_lock_path()`。
- **learning 进程内准入**：`LearningPlane` 准入路径（`_try_execute` 入口、admitted→started 复检点、transport 前终检点，与 foreground 抢占同构的三点）新增 learning 服务屏障退避：learning restart 受理后新任务不再准入（保持 queued，不 busy-wait），存量在飞任务自然排空供空闲门观察；屏障由释放单点撤销后无需干预自动恢复。探测异常 fail-open——learning 自身故障不得把退避变成永久停摆。工厂接线传入 `task_admission_barrier(data_dir, "learning_job")`；未接线时零行为变化。
- **任务注册表（依赖范围准入）**：`runtime/admission_barrier.py` 新增闭表 `TASK_ADMISSION_DEPENDENCIES`（`web_chat`/`web_chat_stream`/`web_queue_dispatch`/`web_schedule_wake` → `web`；`feishu_message` → `feishu`；`learning_job` → `learning`）与唯一读取 API `task_admission_barrier(data_dir, task_kind)`：准入按任务声明的依赖范围检查屏障，未声明的服务重启不外溢（web 屏障不停摆 learning，learning 屏障不阻塞 web 消息）；未登记任务种类抛 `KeyError`——准入范围是声明事实而非调用点自选参数。四个执行入口（web 三路由、调度续跑、feishu bridge、learning plane）全部收敛到注册表，不再散落服务名。
- **诚实边界**：① 本条目所称"缺口②"源自 v0.6.14 缺口①条目的边界注记（"learning 进程内准入未接"）与代码锚点（`_target_busy_reason` 的 no-busy-gate 注释）；原始"设计 v1.2"文档未入库、当前树不可核验，v0.6.14 条目中"设计文档已补 §22 实施记录"的表述不实，特此更正——缺口①的权威实质以 CHANGELOG 条目 + 提交 df103c26a 为准。② 空闲门探测与 plane 准入在单元层验证（含真实跨进程 flock）；未做 learning 真进程 + restart 的端到端编排验证（属部署验收）。③ learning restart 的物理停启仍走 `restart_mirror.sh` 既有路径，本条不改变其语义。
- **data/methods 资产回填**：按 `.gitignore`/AGENTS.md 声明的"learning method assets, committed and preserved"政策，回填历次会话 `save_candidate` 后未提交的 25 个方法目录（已跟踪 276 个中 272 个同为 candidate，跟踪不以生命周期为门槛；内容扫描无密钥/敏感命中，git 安全扫描通过）。

## v0.6.14 — Runtime integrity, fleet foundations and truthful build identity（2026-09-19）

- **重启等待窗口消息准入屏障（设计 v1.2 §8.2/§8.3，缺口①）**：受管服务 restart 受理即原子建立按服务准入屏障（`data/runtime/service-control-barriers/<service>.json`，单一 operation 持有；建立失败受理一并失败并回写 failed，不留"已受理但无屏障"操作）。屏障期内新消息不得成为新 run——web `/chat` 只回带 operation_id 的持久化排队回执（沿用 human_turn_queue，新增 20 条/会话显式上限，超限 503 queue_full 回执不静默丢）；`/chat/stream` 对已领取项服务端回滚 queued（保 FIFO）并回 session_busy 家族回执；`/queue/dispatch` 屏障期不发放 claim；调度续跑（`_deliver_schedule`）在 grant 消费前按屏障退避，不抢占排空窗口；feishu worker 将消息保留在有界队列延迟处理，队列满走既有 QUEUE_FULL 补偿回执。释放按 §8.3 生命周期单点裁决：waiting/受理阶段失败、stale reap、succeeded 全量释放；物理 rc≠0 与 running→failed fail-closed 保留（受影响未恢复）；核验失败按服务粒度——明确判 ok 的服务恢复准入，skip/unhealthy 保留，identity 视图按服务暴露屏障与 owner（`barriers`/`barrier-release` 为操作员覆盖出口，已并入 mutation guard operator CLI 围栏）。准入不对称声明：模型 run 无法阻止另一进程的 HTTP/WS 消息产生新 run（无跨进程准入工具），必须由进程边界机械执行；veto/override = 终态自动释放 + 操作员 CLI。新增 29 项确定性回归（store 24 + web 5），并把 `_verify_restart_targets` 扩为返回按服务 healthy 集（含既有 identity stub 更新）。
- **Release / build 身份分层**：正式语义版本继续由 `pyproject.toml` / Web `SERVICE_VERSION` / README / CHANGELOG / release tag 一致性约束；未打 tag 的开发构建不再冒充最后一个 release，启动 manifest 机械记录 expected/nearest release tag、距最近 tag 的 commit 数、Git SHA、tracked dirty 与 exact-release 事实，Web `/health` / `/api/info` 和 V2 顶栏/设置页显示真实 build identity。
- **会话与模型防串线**：Web resume 绑定精确 run generation；同 run 路由 registry 以 routing epoch 冻结，显式模型切换仍由模型拥有；provider-native 隐藏 replay 只在 exact provider/model/generation contract 下复用；运行时增加薄 `Run Integrity Receipt` 汇总既有机械身份事实，不根据回答文本、system fingerprint 或祖先历史做语义污染裁决。
- **Web 长会话连续性**：EventStore 热读缓存和前端 single-flight/hidden-tab 抑制消除大事件日志轮询风暴；active-run reasoning/text replay 改为 lossless bounded-spool + 相邻纯流片段机械合并，重连保留完整推理进展而不把 tool/terminal 事件混写。
- **Provider / Tool 机械契约**：模型 ID 支持 HF/本地路径/注册短名的唯一归一；lazy schema 保留被真实 first-call 失败证明必要的参数上限/状态机事实；工具失败回执只提供当前能力、Schema、PATH、权限等机械事实，不替模型指定语义修复策略。
- **Browser Semantic Operations 底座**：补齐 Browser Phase 1 perception、SemanticDiff、typed predicate wait、version pressure、mutation receipt 与 bounded semantic operation 的机械边界；否定推断要求完整 coverage，snapshot-local identity 不伪装稳定世界对象，wait timeout 作为 observation 而非自动失败/重试。
- **Fleet 子代理生命周期底座（显式 opt-in）**：Project / ExecutionWorkspace / WorkerLease 最小纵切与 crash/reclaim 门；原子 reclaim + CAS 恢复 + 有界 lease TTL（真实 SubAgentRunner 生命周期内逐轮 renew 心跳）；新增只读 `subagent_lease` / `subagent_topology` 工具——topology journal 与 lease 磁盘真相合并视图，spawn facts 携带 parent_session_id 使重启后可机械恢复归属；factory 生产装配仅在显式 opt-in 下生效，未启用时各面诚实降级；已在 merged main 上完成 live spawn/reclaim qualification。
- **运行时完整性收敛**：缺失会话权威 fail-closed；provider 溢出权威化、无效 provider 投影重建与 exact wire integrity；late child 结果按 run generation fencing；进程状态生命周期上限、lifetime 高水位保留退役；共享服务生命周期权威 fence；legacy shared authority fallback 退役；支持精确双根重启。
- **服务控制与资源治理**：service-control 两阶段 restart（不再等待 lifecycle-lease）；P0-A.1 零写读路径 + controller identity + in-lease binding reverify；P0-B 后台学习的前台真实抢占；LFRT 只读观察者与 admission authority；Web 端 TASK-005 desired/live/stable 服务身份视图（ServicesPanel）。
- **知识 / 记忆 / 方法学习闭环**：学习闭环默认启用（reflection auto + learning plane on）；知识注入观测闭环（receipt_pointer / hydration 登记注入台账）与 P1 注入归因层（A 级机械归因 + per-ref/per-surface 报告）；MemoryExtractor 调度迁入 Learning Plane；记忆近重复聚类报告（只读）与检索 A/B 评测（同系统只换 embedder，改写查询端到端 Recall@5 0%→45%）、threshold 按 embedder 校准、embedding 缓存按向量版本分文件；method discovery v2（freshness 事实）与 record_use 模型使用声明。
- **压缩与缓存连续性**：锚快照块移出 wire 尾部降低前缀扰动；同 run 资源安全字节阀。**勘误（2026-09-19）**：本条曾依据提交 7004b9b89 的信息记录"压缩触发时任务锚点强制 pinning（task_anchor_pin_messages）"；该机制随后在人审收敛修复 edde89582（restore cache-only scope after convergence）中被移出主线，**未包含在本版本发布内容中**，特此更正（对最终树逐项核验，其余各条均在）。
- **Browser SMC 评测与稳定性**：共享 ground-truth fixture（数据化期望 + 服务端事件日志）、GT qualification v01（11/11）与首个 subject-facing 单臂 smoke v01（冻结回执收口）；CDP frame ceiling 参数化 + 硬上限（默认 128MiB）与观测接收预算；capture-loss 分类与 navigate 轻量前置；模型驱动 projection window + evidence-layer vision phase 1。
- **内省工具与 Web 修复**：`method_manage` schema 参数语义澄清（verdict/mechanism/task_benefit/promotion 仅 record_qualification 消费；note 仅随 record_use/record_qualification 持久化；evidence_refs 绑定当次 episode 不自动证明归属；refine 需持久化内容走 save_candidate(parent_ref)——仅描述层，无行为变更）；Web 模型权威改为 session-scoped；流式代码与 KaTeX 预处理隔离；live interjection handoff；review audit 改用 resolved data dir。
- **CI / 门禁加固**：runner-proof 门禁套件（全历史 checkout + fixture git identity）；累计 ruff / pyright 债清零；A.5 覆盖申报协议化（含 merge 增量全路径覆盖与合流定性）；scorecard 冻结协议合同 fixtures；injection ledger env 读取登记进棘轮基线。
- **版本边界**：`v0.6.13` tag 保持不可移动；本版本建立后续 patch 边界。候选在正式 tag 前仍显示 `v0.6.14-dev.<distance>+g<sha>`，只有 exact `v0.6.14` tag 且 tracked source clean 时才显示纯 `v0.6.14`。

## v0.6.13 — Web reviewability and release single-writer boundary（2026-09-12）

- **Release 单写者**：退役会在 main push 时改写既有 draft 的 Release Drafter；tag 触发的 `release.yml` 成为唯一 GitHub Release writer，并继续使用 GitHub 自动生成发布说明。
- **长粘贴 Composer**：输入框可机械扩展至 `min(40vh, 420px)`；单次粘贴 ≥20,000 字符时原文无损转为现有 `text/plain` durable attachment，保留用户任务指令并提供“恢复到输入框”，不做自动摘要或语义筛选。
- **演进审批可查阅**：左侧演进审批项可打开完整 detail/diff 审阅层，展示全文、scope/evidence、影响文件、action 摘要、理由历史和状态时间，并复用既有 CAS / `requires_human` / 拒绝理由审批契约。
- **撤回分级**：Feishu `message_recalled_v1` 从 no-op 升级为机械撤回：尚在 bridge 入站队列、未被 worker claim 的消息直接物理移除；已 claim/已运行的消息不伪装“未发生”，而是按不可变 `feishu:<message_id>` 追加 `message.retracted` 事实，后续 JSON/read replay/fork 上下文统一投影为 `[RETRACTED]`，同时保留原始 `message.appended` 审计。撤回与 `/stop` 保持正交，不由程序擅自等价为中断。
- **版本边界**：`v0.6.12` tag 保持不可移动；本版本建立新的 patch 边界，异常可回滚到 `v0.6.12`。

## v0.6.12 — Stable provider prefixes and cache-efficient working sets（2026-09-12）

- **Sticky compaction frontier**：修复 active run 中 provider-view receipt 副本与 canonical Session 的 compaction marker 分裂；`message.cache_compacted` / `history.compaction_state_reset` 现在在 live Session 与 event replay 保持同一机械语义，避免同一源消息在后续 build 被重复 compact/reset、反复改写 provider 前缀。
- **低收益 rewrite 迟滞**：保留已验证的 64K coarse working-set batch 与 grace 机制；12-result soft cap 只有在 raw→receipt 实际净节省达到 16K 时才提前 fold，32-result hard cap 作为大量小结果机械兜底。真实 2026-09-11 GLM 事故 human-turn 离线重放中，working-set fold 事件由 5 次降到 2 次（-60%），最终 tool 投影仅由 28,131 增至 29,927 chars。
- **Compaction 重放实证**：同一真实事故轨迹在 40K 压力离线重放，首轮 compact 102 个 source messages 后 live markers 同步为 102；第二轮同 provider/model/budget 新增 compact=0、overlap=0，证明 stable frontier 不依赖进程重启/replay 才生效。
- **可归因缓存观测**：常态 `request.meta` 增加 fold trigger、pending raw/receipt/net-gain 等低成本机械事实；显式 `LLM_PAYLOAD_TRACE=1` 时，OpenAI-compatible 发送前 deep trace 记录完整 request-object 指纹、消息公共前缀/首个分叉消息、tools/params shape 变化及 cache/compaction epoch。trace 默认关闭、fail-open，不进入 prompt，也不参与路由/完成判断。
- **架构边界 R9**：正式定义 “Prefix Stability as a Mechanical Resource Boundary”：程序可以冻结机械表示、控制改写频率和物理资源水位，但不得据此判断哪条证据重要、充分或应该删除。`v0.6.11` 已发布且保持不可移动；本修复作为独立 patch 版本，可回滚到 `v0.6.11`。

## v0.6.11 — Runtime identity independent of operator sandbox（2026-09-11）

- **运行身份解耦**：常驻 Web/Feishu 服务不再继承发起 restart 的 MCP Console/IDE/CI 临时 `HOME`/`TMPDIR`；启动器恢复当前 Unix 账户 HOME 与 macOS 原生 user temp，再由 LFL 自身 CatastrophicGuard / EXEC_MODE / approval / EXEC_SANDBOX / workspace scope 实施安全边界。
- **DSH 发现修复**：修正 `restart_mirror.sh` 先设置、随后又误 `unset DSH_HOME` 的启动 bug；镜像继续使用 `data/dsh-home` 隔离 DSH profile/session，同时从真实账户 `~/.local/dsh/bin` 发现已安装 DSH。真实 DSH v0.1.1-rc.2 canary 已返回 `DSH_RUNTIME_OK`。
- **回滚边界**：`v0.6.10` 已正式发布且保持不可移动；本修复作为独立 patch 版本，若异常可回滚至 `v0.6.10`。

## v0.6.10 — Honest sensing, scoped recovery and bounded working set（2026-09-11）

- **失败回执去策略化**：工具不可用时只返回当前状态、原因、PATH/Schema/权限/资源等可机械证明的事实，不再由程序在 failure receipt 中指定安装依赖、切换工具/模型或重试策略；模型保留修复路径与任务策略判断权。
- **会话 provenance**：`event_stream` 默认只读当前 session，并在每条事件中保留 `session_id`；跨会话 workspace 审计必须显式 `scope=workspace`，避免并发 release/测试/其它会话动作被误认成当前会话事实。
- **Active interruption continuity**：历史 event/live 前缀分叉仍 fail-open、绝不猜测合并；若上一真实用户轮在 tool chain 中取消，则从 live session 机械恢复最近模型可见文本与终态工具回执作为一次性 continuity fact，不恢复隐藏 reasoning/tool draft，当前用户输入仍是最终授权真值。
- **Working-set 双机械上限**：保留 64K coarse byte batching 以保护 provider prefix/cache，同时对已暴露、可恢复的 pending tool results 增加 12-result 上限，避免大量小回执长期卡在字节阈值下。真实 2026-09-11 事故回放从 63,979 tool chars 投影到 28,131，61 个旧可恢复结果 receipt 化、pending 仅 2；固定 18×12K benchmark 仍维持 coarse fold cadence（grace0 R7/R13、grace1 R8/R14），未退回已被否决的 per-round rewrite。
- **版本边界**：`v0.6.9` 保持已发布不可移动；本修复集作为新的 patch 版本 `v0.6.10` 验证和发布，出现问题可直接回滚到 `v0.6.9`。

## v0.6.9 — Provider-agnostic honesty and tool-use recovery（2026-09-11）

- **全模型诚实契约**：本地与网络 API 模型统一遵守“当前可核事实先取当前证据”。训练先验、参数内知识、历史经验/记录可用于提出假设与缩小检索范围，但不能冒充已经核对过的当前代码、文件、路径、版本、运行态、配置或外部接口；无法取得当前证据时必须明确未核验/不确定性。
- **工具使用恢复**：保留最小 Common Governance，恢复失败后核当前 Schema/code/docs、自主纠正参数、专业工作流 Skill discoverability，并让默认 `search_files` 优先当前 workspace、避免临时 CI/backup/worktree 的旧源码副本污染当前事实；显式 root 仍可审计历史副本。
- **Provider 无差别**：上述治理位于统一 prompt/tool/schema/evidence 层，不按 Ornith/GLM/MiniMax/DeepSeek 分叉；provider adapter 只承载 wire/reasoning/transport 差异。
- **版本与回滚**：统一 package/Web/README 为 0.6.9；Release tag 必须与 `pyproject.toml` 版本一致，正式发布 remote 明确为 `lfl`，版本异常可回到上一已验证 tag/commit 后再修复。

### M61：工具可达性每轮观测（Phase 0）——EVO-20260903-ba25857b 第一优先落地（2026-09-03）
- **背景**：P0-0 能力可达性缺陷（get_tool_schema(X) 连续 SUCCESS 但 X 未进 provider callable 集、schema-loop 熔断）的演进修复，实施顺序冻结 P0-1→P0-2→P0-3；本轮执行第一优先 Phase 0 观测性（P0-1 状态机/P0-2 no-progress 语义已先行在位，单测 25+ 全过）。
- **新增**（`engine_services/tool_reachability.py`，224 行）：`RoundReachabilityRecorder` 每轮记录 registered_tools / candidate_tools / final_provider_callable_tools / promoted / quarantined / promotion_state 快照及 schema_lookups（get_tool_schema 探测事件）→ emissions（raw_arguments 线上 JSON 串 + arguments 解析态）→ executed（真实回执 + duplicate-guard 阻断帧 blocked=True 如实区分）全链；JSONL 每轮一行落盘 `data/observability/tool_reachability.jsonl`（env `TOOL_REACHABILITY_LOG` 覆盖，`off` 禁写）；flush 成功即清当前轮（防重复落盘）并留 last_flushed 快照。
- **接线**（`engine_services/tool_cycle.py` 六点，全 fail-open）：`__init__` 持有观测器；投影入口 begin_round（round 取 promotion 跨 run 单调投影序号，利于 incident 对齐）；enforce/shadow/off 三分支投影快照同口径入记录；promotion resolver 探测事件入记录；`_execute_tools` 声明链（含缺 id 声明 valid=False）+ 回执链 + 逐轮 flush。纯观测面：不读不写 run state、不做决策、任何失败降级 debug 不阻断主循环。
- **测试**：`tests/unit/test_tool_reachability.py` 10 用例（全链 JSONL/fail-open 不可写/env off/env 覆盖/flush 幂等/防御路径形状/schema 名提取/promotion 快照/resolver 接线/观测器持有）+ 既有 promotion/no-progress/duplicate-guard/stagnation/tool-round-tail 回归 70 passed（合计 80）。

### M60：Web 新建会话继承模型覆盖——修"飞书新建会话变成本地模型"（2026-09-03）
- **症状**：新建会话后模型回落装配默认（本地模型），丢失用户此前所选云端模型。
- **根因**：三端"/new 继承 model_override"仅 CLI（M52）与飞书（M52-fix）落地；Web `/api/v1/chat`·`/api/v1/chat/stream` 的 `new_session=true` 分支仍裸 `create()`（override=None）。owner 飞书私聊与 Web 跨端共享当前会话（shared_current），Web 侧新建的 override=None 会话被飞书经 `get_shared_current()` 拉走 → 回落本地默认。
- **修复**（`web/routes.py`，新增 `_inherit_shared_model_override`）：Web 两端点新建会话前继承旧共享会话 `model_override`（fail-open → None，旧会话缺失/损坏不阻断新建），与飞书/CLI 同语义；用户在请求中显式携带 `model` 时仍按既有语义接单后覆盖（EVO-20260829-ad8c5984 不变）。
- **测试**：`tests/unit/test_m60_web_new_session_inherit.py` 4 用例（chat 继承/无共享 fail-open/损坏 fail-open/流式继承）+ 既有 M52/M50/locks/stream/csrf 回归 57 passed；ruff PASS。

### R9-B3 Phase 3：两依赖环断裂 + cycle 守卫恒 0（2026-09-01）
- **环① engine<->build 三步**：`build_session_snapshot_text` 纯 move 至 `core/session_snapshot.py`（`1aba90b`）→ build.py 函数内 import 退役改指叶子模块断环（`ac7b7c6`）→ engine re-export 清理、包级导出源直连（`2bc4784`）。
- **环② session<->fork 四步**：`session_types` 纯类型抽离（SessionIdConflictError/ForkReport/BranchSeed，`f98b527`）→ fork 异常 import 改指（`3e6cf72`）→ BranchSeed 重建入口 + fork 收窄为数据生成、持久化职责移交（`95c5724`，环断点）→ BranchWriter Protocol 依赖倒置窄口（`fa51dc9`）。
- **守卫翻转**：cycle 守卫恒 0 断言生效、known_cycles 空态锚定（`f54a8e7`）；Tarjan 双侧实测 0 环，断环后依赖全单向 DAG（fork 唯一出边 = 纯类型模块）。
- **等价性**：全程 wire-fixtures 逐提交回执（21 用例）+ 环② fork 回放三面对照 + 等价套件 133/133；八连提交链机检五规则逐条 PASS、每步可 bisect。
- **治理事件**：外部滞留测试代收口 9 文件（`2dc9b3b`）+ 提交流程文档化（`3271c1e`：提交队列串行化/共享主区安全纪律/外部红登记豁免口径）。

### R9-B2 Phase 1+2：worktree/门禁/机检 + 架构守卫四检测器上线（2026-09-01）
- **守卫资产收编 + 基线 v2**（guard）：workbuddy 雏形转正（`ff37e92`，HEAD 口径逐键校准）；`function_size_baseline.json` 升级五节 schema:2（`legacy_super_functions`/`function_lines` 37 键/`local_imports`/`known_cycles`/`exemptions`），全数值节 HEAD 棘轮只降不升（`179b375`）；守卫文件更名 `test_arch_guards.py`。
- **四检测器**（guard，spec §5.3 三层红线 + 棘轮 + cycle）：三层红线 300/200/WARN 120-150 三态（`837eb51`）｜棘轮防篡改纯函数化 + import 守卫行内豁免标记（`2e10219`）｜runtime cycle 检测器 AST 依赖图 + Tarjan SCC 实测恰两环（`2aa50af`）｜守卫读源双口径——外部未 staged 漂移回退 HEAD、真实违规全量设防（`dbf340f`，外部级豁免归零）｜豁免清单数量单调不增（`2d9eb03`）。演练发现并修复语义缺陷：强制登记线 150 与 WARN 下限 120 解耦（`658f1df`）。
- **门禁与机检**（chore/fix）：commit 性质机检五规则 + `r9_commit.sh` 三步包装（`f871d66`，前缀白名单/行为面隔离/wire 回执/守卫防篡改/switch 前缀）；ruff 存量清偿 + ci_gate 第 1 步全量阻断、外部级 D-07 区分呈现（`ae6faca`+`54743b1`）；旧守卫 `_base=1361` 口径冲突退役（`f0dcc16`）；守卫性能 24.98s→1.32s + tier0/markers/ci_gate 三层接线 CI 常驻（`cebdebc`+`0238c2a`，全链路 56.1s）；机检空 diff 崩溃修复（`2cf7a79`）；xdist 假红降级——红→serial 单点复核（`ace4f3e`，门禁语义 = serial 可复现红才阻断）。
- **演练回执**：七场景红/黄/绿全矩阵（tmp 构造树 + /tmp worktree 端到端各一轮）；12 commits 逐条机检单性质全过（bisect 可判定）；外部混合层 69 项零触碰（交集=0 实证）。

### R9 结构收口准备：三批默认值切换 + 行为基线固化（2026-09-01）
- **立即项四件**（refactor/fix）：删除 tests/unit 四源码副本 1994 行死代码（`c6f9f4e`）；path_registry 隔离洞双修——静默 fallback 改抛错 + 测试沙箱 chdir 锁（`5c5df12`）；dev extras/lockfile 可复现安装口径（`69e154b`+`046bd34`）；symlink 探测三态化——edit_file 探测失败也拒写（fail-closed），read_file 如实标注不拒读（`347af8f`+`64beb97`）。
- **测试工作流**（test/chore）：tier0 冒烟集（338 用例 14.8s 分钟级反馈）+ xdist 并行化（全量 13min→36s，失败集合与串行一致）+ `ci_gate.sh` 一条命令复现 CI 三件套（`0fc28e3`+`65aa515`+`6fb94b0`）。
- **Phase 0 三批默认值切换**（每批独立可 revert，批间以镜像流量观测回执为门）：`LFL_EVIDENCE_CAPSULE` on→off（`79376ef`，W1 观测：任务完成 7/7、dup 0%）→ `LFL_TOOL_GUIDANCE` on→off（`cfda166`，W2：完成 4/4、失败自恢复全靠事实性回执零引导依赖）→ `CACHE_GUARD_PERF_BLOCK` on→enforce（`6a137ef`，W3：guard 判定 63 条全 ALLOW 零误拦、privacy 硬拦照旧）。
- **BEHAVIOR-BASELINE-R824 行为基线固化**（`372aae6`）：六道硬门全 PASS（wire 零程序注入/潜语义通道/advisory/capsule/suspect provenance/性能类 BLOCK 全部 chars=0 或 WARN 化）；R8.24 fixed-point 达成；behavior canary 解除，后续结构重构（R9 Phase 1+）以本基线为只读对照。
- 详见 `docs/r824/BEHAVIOR-BASELINE-R824.md`（复现口径：`uv sync --frozen --extra dev` + `env -u` 七开关干净进程 + `--dist loadfile -n 8`）。

### 任务接力热卡 + 紧急压缩空转修复（2026-08-26）
- **任务接力热卡机制**（feat）：用户中途切换意图时，自动生成「热卡」（上一任务关键进度/证据/下一步摘要）注入新上下文——任务交接连续性保留，无需翻档案从头恢复；含单元测试（test_task_hotcard.py）。配套规则：RULE-AI-20 第 7 条「意图切换即时登记」。
- **紧急压缩空转修复**（fix）：历史压缩预算原先只统计消息正文（content），不含思维链（reasoning_content）与工具调用参数——实测部分会话思维链占比 40%+，导致「提交超模型窗口被守卫拦截 → 紧急压缩判定未超预算不缩历史 → 下轮仍超限再拦截」空转死循环（会话 fb8f8987 连续 3 次紧急压缩后历史体积 300K 纹丝不动）。现改为按全字段（wire 口径）统计，紧急压缩后历史真正缩小，下轮提交恢复。

### 压缩风暴熔断（P0 breaker）+ 缓存遥测内容/传输分层（P1）（2026-08-25）
- **背景**：8/24 命中率 98.2%→87.8% 归因 = 两个大上下文会话进入「压缩风暴」（每轮归档 20-90 条消息 + 锚点持续前移 → 历史字节每轮被改写 → provider 前缀缓存只命中 system+tools 固定段 8,320 tokens，命中率钉死 3-4%，连续 40+ 轮）——去掉两个异常会话后 deepseek 命中率回到 97.2%（审计 `guarded_requests.jsonl` 复算）。风暴根因 = 有效预算（窗口×0.6×0.5≈300K 字符）与重工具会话体积的剪刀差，cache monitor 的 `force_head_keep` 恢复条件（锚点连续 N 轮不前移）在风暴期永不满足 → 自持。
- **P0 compression-storm breaker**（`cache_health.py` + `history.py` + `build.py` + `engine.py`）：
  - 触发 = 连续 (context.compressed 且 anchor 前移 且 压缩后仍超压缩线) 达 `BREAKER_TRIGGER_RUNS`（默认 5）+ 命中共信号（独立滚动窗口 < `BREAKER_HIT_THR` 0.5，防渐进折叠误判——折叠轮命中高）。
  - 冻结 = 禁止程序兜底压缩 + 锚点不前移（`freeze_compression` 进 `build_history_messages`，不归档/不分层降级）；冻结期超安全水位（预算×0.95，与 cache_guard 规则 F BLOCK 阈值对齐）→ `context_pressure` 前置拦截（不提交——AI 先 checkpoint/换会话），规则 F 在 breaker 期降级 WARN（防双拦死锁）。
  - 退出 = 明确 hysteresis：cooldown 轮数下限 + 上下文低于退出水位（预算×0.8）+ anchor 连续稳定，非仅时间。
  - 逃生 = 连续 context_pressure 达 `BREAKER_PRESSURE_ESCAPE_MAX`（默认 6）→ 放行一次受控压缩（烧损有界，防永久死锁）。
  - 审计 = `data/audit/cache_breaker.jsonl`（storm_count/anchor/breaker_enter/breaker_exit/context_pressure/escape_armed + reason），复发可直接从 JSONL 判定；`architecture_status`/snapshot 暴露 per-session 熔断状态。
  - 水位口径：锚定视图字符（实际提交量）——锚点压缩不删会话消息，全量口径会让压力永不解除。
- **P1 遥测内容/传输分层**（`engine.py` + `build.py` + `cross_sync.py`）：
  - 问题：程序把 `⚡ 缓存命中率` 写回 assistant 历史 → 下一轮 LLM 可见 → 模型可模仿伪造同格式行（实测 8/25 msg[128] 同条消息出现模型伪造 93.6% + 程序真实 90.4% 双行，伪造行分母 773,371 在审计中不存在）。
  - 修复：`assistant.content` 只存纯回答；权威遥测进 `metadata.cache_health`（结构化）；build 时剥离 legacy 历史中的 ⚡ 行 + 剥离模型本轮伪造行；transport 层（web 返回值 / 飞书 cross_sync）渲染 canonical 一份。
- **PROGRESSIVE_FOLD_K=3**（.env 开启）：P0/P1 之后启用——每次最多折最老 3 个配对组，平滑 anchor 跳跃曲线（非消灭压缩；超 95% 预算保命兜底仍突破上限）。
- **验证**：单测 +12（`test_cache_breaker.py` / `test_cache_breaker_engine.py` 全链路：风暴→breaker→context_pressure→逃生→恢复，含不误触发/隔离/规则 F 降级），全量 2222 passed；真实 DeepSeek 重工具长会话冒烟（逐 request 曲线）。

### SWE 对照实验定论：本地 thinking 默认开启（回退早前"默认关闭"决策，2026-08-24）
- **实验**：同一任务（SWE-bench requests-2317）、同一模型（qwen3.8-27b）、唯一变量 = `LOCAL_ENABLE_THINKING` 开关，判据只有 F2P（`test_encoded_methods`）。
- **结果**：关思考 4 次独立尝试 **0/4 通过**（全漏第二修复点 `sessions.py builtin_str`）；开思考 1 次 **通过**（对照实验 + wire 抓包 `B'GET'` 溯源，双点修复，回归 135 通过无确定性回归）。
- **结论**：本地 27B 的能力边界 = 思考深度——缓存/内存优化解决"跑得更快"，thinking 决定"能否修对"。早前"本地默认关思考提速"的决策被实证否决。
- **变更**：`client.py` 本地 thinking **默认开启**（不再发 enable_thinking=False）；`LOCAL_ENABLE_THINKING=0` 显式关闭（纯速度场景）。测试双态断言更新。完整过程见 `docs/swe_ab_report.md`。

### 缓存窗口镜像：让"缓存里有什么"可见可审计（2026-08-24）
- **能力**：每轮把服务端上报的 `cached_tokens`（前缀命中 token 数）映射回提交载荷的**消息级窗口**——缓存覆盖到哪条消息、哪些是新增（miss 区）。落点：事件日志 `cache.window` 事件（完整可回放）+ `architecture_status.context_usage.cache_health.window`（AI 每轮自查）。
- **信息补充决策原则**（对齐前缀缓存语义，RULE-AI-00）：①补充=尾部追加（前缀不变, miss 仅新增段）；②引用缓存区内信息=零额外 prefill；③中插/重排/压缩=断前缀（当次全量 miss）。
- **实现**：`src/llm_loop/core/cache_window.py`（纯函数 `describe_cache_window`）+ engine 事件钩子 + factory 快照合并；测试 `tests/unit/test_cache_window.py`；文档 `docs/cache_window.md`。
- **实证发现（工具轮模板硬约束）**：llama.cpp Qwen 聊天模板要求载荷含 user 消息——零历史工具轮只发配对组会 500「No user query found」；`_tool_round_zero_tail` 已修复为 [最近 user 指令 + 最近完整配对组]（中间轮次裁剪，任务锚点摘要补偿）。

### 本地模型"出错"根因修复：系统代理劫持回环 LLM 请求（2026-08-24）
- **根因**：httpx 默认 `trust_env=True` 经 urllib 读取 **macOS 系统代理**（Surge 等代理工具把 `127.0.0.1:6152` 设为系统代理）→ **所有 LLM 请求（含本地回环直连）被转给 Surge 代理** → Surge 无法代理自身回环 → 503 Connection Closed（SGErrorDomain）→ 表现即"本地模型出错"。curl 直连正常（不走 urllib）而 LFL 全挂——本地模型 2026-08-22 能用是因为当时 Surge 系统代理未开启。
- **修复**：`LLMClient.__post_init__` 本地 base_url（localhost/127.0.0.1）→ `trust_env=False` 直连（llama-server KV 前缀缓存本就依赖同 slot 直连）；远程 provider 保持默认（需代理访问 API 场景零回归）；env `LLM_TRUST_ENV` 显式覆盖（1=启用系统代理/0=禁用）。
- **实测（Qwen3.8-27B 直连）**：一般形态 精确重发命中 99.5%（1.87s→87ms，21 倍）、前缀+追加 97.3%；工具轮形态 命中 98.4%（1.13s→365ms）——「稳定前缀 + 尾部追加」在本地成立的实证。
- **附带假设（待验证）**：deepseek 大上下文流式断连（incomplete chunked read）可能部分是 SSE 长流经 Surge 代理被掐断——可用 `LLM_TRUST_ENV=0` 让远程也直连对比断连频率。

### 本地模型高缓存命中：工具轮极小窗口默认启用 + 配对组修复（2026-08-24）
- **方案**：本地工具轮「稳定前缀 + 极小窗口」——system prompt + 工具白名单 schema 字节稳定（记忆/快照/提醒全部尾部追加，此前已落地），工具轮只发 system+工具+最近**完整协议配对组**（assistant(tool_calls)+全部 tool 回执）→ llama.cpp KV 前缀复用命中（LMS_DIRECT 直连 llama-server 已是默认路径，注释实测命中 97% / prefill 秒级）。
- **改动 1（默认启用）**：`data/providers.json` local 条目加 `"tool_round_zero_history": true`（ProviderSpec 新字段，env `TOOL_ROUND_ZERO_HISTORY` 显式覆盖；云端缺省 False 零回归）——工具轮历史从 8000 字符预算进一步收成极小配对组。
- **改动 2（配对组修复）**：原 `base[-2:]` 在并行多工具回执时截断声明↔回执配对组 → C1 协议违规（"声明 3 个调用仅 1 条回执"）；改为从最后一条 tool_calls 声明起保留整组（`_tool_round_zero_tail`）。
- **改动 3（可观测）**：`scripts/local_cache_probe.py` 三实验探针（A 冷/B 同 payload/C 前缀+追加），直连 llama-server 验证 KV 命中率与 prefill 提速。
- **附带**：修复 `test_client_params_no_auth_provider` 环境敏感（本机有 llama-server 时直连发现返回真实 key）——隔离 `_discover_llama_server` 使测试环境无关。

### deepseek 大上下文断连修复：预算收敛 1M→150K + 流式断连自动重试（2026-08-24）
- **根因**：`.env` HISTORY_MAX_CHARS 与 `data/providers.json` deepseek `history_budget_chars` 均为 100 万字符（2026-08-18 缓存方案 A 显式豁免）——`[预算预警]`（80%）与程序兜底压缩（90%）被推到 800K/900K 字符，飞书长会话膨胀到 150K-230K 字符仍 0 次压缩、AI 从未收到压缩信号；deepseek 在该量级流式偶发 `peer closed connection (incomplete chunked read)`，断连整轮 50 万+ tokens 白烧（实测 535s/1.26M tokens 的 run 中断，飞书侧表现为"出错了"）。
- **修复 1（预算校准）**：`data/providers.json` deepseek `history_budget_chars` 1000000 → **150000**（≈75K tokens）。既有机制自动前移生效：80% 预算预警 ≈120K 字符注入、90% 程序兜底压缩 ≈135K 字符触发（原文另存 + `[上下文压缩]` 标注，零丢失可 search_archive 检索）；提交载荷被约束在观测失效线（150K+）以下。与 EVO-20260818「收敛上限 1M→200K」既定方向一致。
- **修复 2（断连重试）**：`LLMClient._stream_openai` 对传输级断连（httpx NetworkError/ProtocolError，含 peer closed / incomplete chunked read）在**尚无任何输出已产出**时同请求自动重试 1 次（env `LLM_RETRY_DISCONNECT` 可调/关，默认 1）——前缀缓存命中率高、重试成本极低；已有 content/reasoning/tool delta 产出则不重试（防 UI 重复/工具重复执行）。
- **预期代价（明示）**：压缩轮必断一次前缀缓存（物理必然），缓存命中率从 ~99% 周期回落到 ~86% 量级；换取不再整轮白烧与飞书"出错了"。实测三会话 0 压缩的根因由「AI 忘了压缩」修正为「预算校准缺口」——机制齐备，缺的是预算落在服务端稳定区间。

### 历史预算基准更新 + 缓存命中修复（审查完善项，2026-08-17）
- `history_budget_chars` 全局基准 60000 → **800000**（预算链修复：此前预算过短导致历史截断/提交不完整 → 前缀缓存 0 命中；修复后命中率 98%+）
- 缓存纪律沉淀：system 前缀锚定 + 压缩留缓冲 + M58 命中可观测

### 安全：playwright 子进程加固——cwd 限定 + env 敏感键剥离（DSH 复核 005 建议 a+c，2026-08-16）
- 子进程 `cwd` 限定 `data/e2e/<session>/`（模型代码相对路径访问被限定在产物目录；
  产物路径改绝对路径注入，功能不变）
- 子进程 `env` 剥离敏感键（KEY/SECRET/TOKEN/PASSWORD/PASSWD/CREDENTIAL 子串匹配），
  消除模型代码经 `os.environ` 读取凭据的面
- 文件头安全模型更新：明确"门槛非沙箱"——绝对路径访问与同用户权限（ctypes/syscall）
  仍可达，定位为挡误操作/粗注入，不宣称沙箱；开放面（文件/网络信任边界）仍待产品决策
- 行为变更：模型代码相对路径不再指向仓库根，指向会话产物目录

### 安全：playwright 执行防线补强（DSH 独立审查后修复，2026-08-16）
- **URL 沙箱 host 精确校验**：原正则无 `$` 锚定，`userinfo@host`/域后缀可逃逸（如
  `https://a.feishu.cn@example.com/`）；现改用 urlparse 解析 hostname 精确集合校验
  （仅 feishu.cn 含子域/localhost/127.0.0.1），同时修复裸 `feishu.cn` 误拦与大小写不敏感
- **命名空间隔离**：模型代码经 `_run_model` 在独立命名空间 exec，仅可见 helper 七件套+
  内置；`_page/_browser/_pw/_OUT` 内部对象不可见——堵死"裸 API 直连绕过白名单"路径
- **AST 门控纵深**：新增拦截动态导入（`__import__`/`import_module`/getattr 间接引用）、
  动态执行（exec/eval/compile）、`sys.modules` 取已加载模块（任何访问形态）
- **明确开放面**：模型代码在子进程内可读写工作区文件、发起任意网络请求，属设计未承诺
  防护的信任边界，需产品方显式决策
- 附：DSH 工具 DSH_HOME 可写性回退（长驻 agent 沙箱下 ~/.dsh 不可写时回落项目内 data/dsh-home）

### 安全：提交安全扫描——防 AI 自动提交误传敏感/私密/错误文件
- `scripts/git_security_scan.sh`（pre-commit 钩子 + CI job）：拦截 data/ 运行时数据、.env*/日志/私钥、
  高价值密钥模式（sk-/AKIA/ghp_/app_secret 等）、本地绝对路径（用户目录、/home/）、>1MB 大文件
- `.githooks/pre-commit` 提交前硬拦截（AI 自动提交无人工检查环节）；CI `security-scan` job 全树兜底
- 清理存量：已跟踪文件中的本地用户目录路径痕迹全部中性化（占位符/样例路径）（占位符/样例路径）

### 新增：playwright_exec(code) 单 exec 浏览器工具（EVO-20260816-bfb9f215 阶段二）
- 模型写 Python 一次调用打包 navigate+act+extract，预置 helper 七件套（goto/click/fill/wait/js/screenshot/axtree_text）
- 每次调用独立子进程（解释器/浏览器零跨调用持久），产物落盘 `data/e2e/<session>/`；confirm 二段确认默认 dry_run
- 安全：AST 静态门控禁止 import playwright（强制走 helper）；helper goto 强制 URL 白名单（复用阶段一校验）；子进程超时终止（默认 60s 上限 300s）
- 工具描述钉死 ≤2KB helper 摘要+状态契约+fetch-first"何时不用"条款（对齐 Hermes 调研 #1/#2/#6/#7）
- 验收基准 `scripts/bench_playwright_exec.py`：5 个网关 Web E2E 任务 × 3 次重复（方法论评测纪律第 5 条首单，需网关在线时人工触发）

### 安全：playwright 执行门控升级——注册层门控 + 执行层 URL 再校验（EVO-20260816-96215428）
- RUN_MODE=ptc 隐藏 `playwright_test`（浏览器执行类工具仅 standard/creative 可见，对齐"仅 terminal 权限会话注册"精神），为 playwright 单 exec 演进扫清安全前提
- `playwright_test` 真实执行路径增加执行层 URL 沙箱再校验（纵深防御，参数层之外的第二道）
- 新增 tests/unit/test_playwright_gate.py（3 用例）+ run_mode 四模式可见性断言

### 新增：DSH 编排工具集——调度 DeepSeek Harness 执行任务（P0/P1/P2）
- `dsh_task`：进程级子代理（spawn `dsh --profile headless "<task>"`）——任务下发/超时整树终止/退出码五态映射/3 万字符截断/审计落盘；协议 v2 支持 `ctx_path`（上下文文件引用并入）、`report_format`（结构化汇报模板）、`acceptance`（验收清单逐项自检）、`retry`（失败新 session 重试，timeout 不重试）、任务文本脱敏（敏感 env 值替换）、`background`（JobRegistry 后台执行，多任务并行 fan-out）
- `dsh_session_read`：DSH session 事件日志回放（zstd JSONL）——最终回答 + 工具调用轨迹 + 关键词过滤/指定 session 检索，补全"只回最终文本"的中间过程盲区
- 新增依赖 `zstandard`

### 修复：长任务重启保护——重启预检 + feishu 中断补偿 + guard 去抖
- `restart_system.sh restart` 前检测 feishu 处理中消息（心跳 `processing_msg_id`）——长任务进行中警告确认，防重启打断导致无反馈
- feishu 桥优雅退出打断长任务 → 落盘补偿记录 → 下次启动主动回复"任务因重启中断请重发"（防静默丢失）
- guard 工作区变更日志 5 分钟去抖（agent 长任务编辑期间不再每 21s 刷屏；flag 仍每次刷新）

### 新增：memory 命中计数事实源——升格判据量化（EVO-20260816-fcdbe2e9）
- `MemoryEntry` 新增 `inject_count`/`last_inject_at`：只计**实际注入上下文**（检索构造注入消息的最终 top_k 条目），与 `access_count`（检索命中，含未注入的噪音）区分
- 技巧升格通道（"命中复用 ≥3 次 → 升格经验库"）由此获得程序侧量化判据：`architecture_status.memory.top_injected` 可查按注入次数降序的头部条目
- 计数内存态更新，沿用 run 末 flush() 批量落盘（不新增写盘点）；计数失败 fail-open 不阻塞记忆注入；旧索引无新字段加载默认 0（向后兼容）

### 优化：降级提示 stamp 限频——同类降级 24h 内主消息流只提示一次
- 同一降级对（from→to）重复降级时，提示消息 24h（`FALLBACK_NOTICE_COOLDOWN_S` 可调，0=关闭）内仅注入一次；stamp 落盘 `<data_dir>/state/fallback_notice_stamps.json`，重启仍生效
- 仅抑制消息注入：status 降级态 / 审计 / action_trace 每次照常记录（可观测性不降级）；链全失败汇总不限频（每次如实告知）

### 新增：工作区变更感知——guard 检测 + 提醒重启（P1-12）
- **背景**：运行中进程不感知工作区变化（.env/providers.json/src/skills 改动需重启生效，外部编辑/git pull/agent 自改后一直跑旧状态）
- **机制（手动确认式，不无差别自动重启）**：guard 每轮对监视文件做内容哈希指纹对比基线；变化 → 写 `data/workspace_changed.json`（变更清单 + 建议命令）+ guard.log 记录，**不自动重启**；AI 经 `architecture_status.workspace_changed` 自查可见；确认后 `restart_system.sh restart` 末尾自动 ack（清 flag + 刷新基线闭环）
- 端到端闭环实测通过；相关测试 230 全绿

### 修复：飞书收到回复后多一条重复 [跨端同步] 消息（P1-11 竞态）
- **根因**：`CrossSyncWatcher`（飞书←Web 增量同步）的基线刷新（`mark_processed`）原在**回复发送后**才调用——回答落盘与基线刷新之间存在秒级窗口，轮询（1.5s）会插入其中，把桥自己的回答当"Web 侧增量"重复推送一条 `[跨端同步]`（用户反馈重复）
- **修复**：① `mark_processed` 前移到 `engine.run` 返回后立即执行；② `cross_sync` 新增 `skip_fn`——**按会话精确跳过**桥正在处理的那个会话（其他会话照常实时同步，增量不丢：基线未推进, 清除后按累积 diff 一起推）；两保险消除重复且不牺牲跨端实时性
- 飞书测试 191 全绿（含按会话跳过语义用例）

### 新增：RULE-AI-12 模型身份声明约束（0814 身份幻觉真阳性实证条款化）
- 规则条款：对自身模型身份/提供方的声明必须以 model_catalog / architecture_status 回执为准，
  禁止依据训练先验自报身份；无回执佐证如实声明"未核验"
- prompt 注入 + `docs/ai_rules.md` 条款 + 评测判定器 `verdict_identity_verified`
  （先验身份幻觉判 False；否定澄清/未核验如实声明放行）+ 评测场景 rule12 系列

### 修复：declaration 判定器 B2/B3 误报治理（EVO-20260815-640fc96a，honesty_rate 归因）
- B2 计划陈述豁免：未来时态/规划句（下一步/计划/待办/即将）不抽取；含完成标志的计划句仍校验
- B3 引用内容剥离：代码 fence / 表格行 / 引用块不进入声明抽取；正文完成声明不受影响
- 真阳性约束测试：身份幻觉句与严格行为声明仍被捕获（宁可误报不可漏报）
- docs/eval_scenarios.md 新增「判定口径已知边界」文档（能力/计划/引用豁免、比较保留严格、身份最严）

### 新增：真实 tool-call 往返门禁（EVO-20260815-f22ab8dd，v0.6.5 arguments 透传回归补洞）
- run_real_smoke.sh 新增 [1.5/3] 真实 tool-call 往返用例（协议矩阵：默认 openai +
  SMOKE_WIRE_PROTOCOL=anthropic|google 逐协议执行，无 key 自动 skip）

### 其他
- 进程代码时效提醒（EVO-20260815-69ac0bd0）：每轮末检测工作区/进程代码时效，每进程冷却一次
- refresh_config 生效范围说明（LLM 凭据/模型目录热生效，其余启动时装配）
- 门禁 pytest 全量绿 + ruff 0 + pyright 0 + CI 三件套 + nightly 真实评测通过

## v0.6.7（2026-08-16）

### 修复：history_anchor 落在工具轮内 → 孤儿 tool 回执 → 上游 API 400（tool_call_id is not found）
- 根因：锚点（P1-10 窗口裁剪起点）落在「工具调用声明 ↔ 工具回执」消息组内部时，
  声明被裁掉、回执成孤儿 → OpenAI 兼容 API 拒绝（tool_call_id is not found）
- 双层修复：① `build_history_messages` 裁切后丢弃窗口内无对应声明的 tool 回执
  （declared_ids 集合 + dropped_orphans 计数，如实告警）；② 锚点推进对齐——锚点若落在
  工具回执上则拉回至其声明起点，保证组内声明/回执成对进入窗口
- 回归防护 +1（tests/unit/test_anchor_pairing_boundary.py：锚点落在工具轮内/外两方向配对断言）
- 门禁 pytest 2058 passed（25 本地文档基线 skip / 14 real_llm 排除）+ ruff 0 + pyright 0；
  线上实测（kimi/k3 真实 tool-call 往返）正常

## v0.6.6（2026-08-15）

### 修复：tool_call.arguments 归一化回归（v0.6.5 引入，工具通道断连根因）
- 根因：v0.6.5 客户端重写时本地重定义了 ToolCallDeltaAggregator（原版从 llm/schemas.py 导入），
  新实现 finish() 不解析 arguments → 真实 provider 的 JSON 字符串 arguments 原样进注册表 →
  所有工具调用被 "[参数错误] 参数必须为 JSON 对象" 拒绝（FakeLLM 预构造 dict 的测试盲区）
- 修复：复用 schemas.py 聚合器（finish 含 json.loads 归一 + _raw_arguments 兜底）；
  Anthropic tool_use start 空 input 不并入（防 "{}" 破坏 JSON）；Google functionCall 独立 index
- 回归防护 +4（归一/非法兜底/端到端真实客户端 mock SSE→read_file 真实执行/注册表防线）
- 门禁 pytest 2090 + ruff 0 + pyright 0

## v0.6.5（2026-08-15）

### P3-5：provider 广度——Anthropic / Google 原生协议（wire_protocol）
- LLMClient 协议分发：`openai`（默认零回归）/ `anthropic`（Messages API：/v1/messages + x-api-key +
  anthropic-version，system 拆分、tool_use/tool_result 转换、thinking_delta/input_json_delta 流式解析）/
  `google`（Gemini：streamGenerateContent?alt=sse + x-goog-api-key，contents/systemInstruction/
  functionDeclarations，functionCall 聚合、MAX_TOKENS→truncated）
- 元数据驱动：ModelSpec.wire_protocol（providers.json 模型条目，非法值回退 openai 如实告警）；
  client_params/pool/factory 全链透传；LLM_WIRE_PROTOCOL 可配默认 client
- 修复：Python 3.11+ 裸 yield-from 丢弃子生成器返回值（终态 LLMResponse 必须显式捕获 return）
- 测试 +7（anthropic payload/头/tool_use 聚合、google payload/functionCall/截断、默认零回归、
  provider 解析/非法回退）；门禁 pytest 2084 + ruff 0 + pyright 0

## v0.6.4（2026-08-15）

### P3-4：workflow_run DAG 编排（拓扑序 + 节点级预算，无 graph DSL）
- `mode=dag`：步骤可声明 `id` + `depends_on`（id 或 0 起下标）依赖；Kahn 拓扑排序确定执行序，
  依赖步骤 final_answer 自动注入被依赖步骤 context（【依赖步骤 X 结果】标注）
- 校验诚实：未知依赖/自依赖/重复 id → 400 式如实失败；**循环依赖 → 拓扑前检测**（不派发任何步骤）
- **节点级预算** `budget_rounds`：透传子代理 max_rounds（SubAgentRunner.run 新增可选参数，
  提示文案与循环守卫同步生效）；回执如实标注 budget
- parallel/pipeline 同步支持 budget_rounds（通用节点预算）
- 测试 +6（拓扑序+依赖注入/环检测/未知依赖/自依赖/重复 id/预算透传）；门禁 pytest 2079 + ruff 0 + pyright 0

## v0.6.3（2026-08-15）

### P3-2：英文文档对等化
- `README.en.md` 整体重写为与中文版对等（157 行，章节/功能 27 条/配置表/CLI 命令逐条对应；程序输出标记保留中文原样，与源码字面一致）
- 新增 `docs/api.en.md`（142 行，章节数与中文版一致 19 段）与 `docs/ai_rules.en.md`（217 行，RULE-AI-00~11 全部编号对等）
- `docs/INDEX.md` 链接补充；英文文档对等守护测试 +3（api 章节数/规则编号/README 版本一致）

## v0.6.2（2026-08-15）

### P3-3：bash 沙箱后端（EXEC_SANDBOX=bwrap|none，可选）
- `EXEC_SANDBOX=bwrap`：bubblewrap 隔离 execute_command——只读系统目录（/usr /etc /lib /lib64 /bin /sbin）、
  /dev /proc 挂载、/tmp 临时文件系统、工作区可写绑定、独立 PID/UTS/IPC 命名空间
- **fail-closed 语义**：显式开启而 bwrap 缺失 → 命令不执行、回执如实说明（不静默降级）；
  回执标注"已启用 bwrap 沙箱"
- 前台/后台（run_in_background）双路径接线；未启用零回归（shell=True 路径不变）
- 测试 +8（argv 结构/禁用/启用/缺失 fail-closed/回执标注/后台/零回归）；门禁 pytest 全绿

## v0.6.1（2026-08-15）

### P3-1：MCP 客户端接入（stdio）
- `MCP_SERVERS` env JSON 配置 stdio MCP 服务器；启动连接握手（initialize/initialized/tools/list）
- 工具以 `mcp.<server>.<tool>` 名注册（inputSchema 透传为 parameters），执行走统一注册表通道
  （线程超时 / 输出分层 / 审计复用）；结果五态包装（success/failure/blocked/timeout/error）
- 诚实边界：单服务器连接失败 fail-open（其余服务器/工具不受影响）；调用失联单次重连，
  仍失败 → ERROR 态如实；isError → FAILURE 态（content 原样透传）
- 测试 +10（配置解析/真实 stdio 握手与清单/schema 透传/五态/注册表集成/双服务器 fail-open）
- 门禁：pytest 2062 passed + ruff 0 + pyright 0

## v0.6.0（2026-08-15）

### 窗口锚定：历史起点固定 → 前缀缓存全量命中（P1-10）
- **根因**：预算裁剪"从最新往回保留"导致每次提交的保留集合**起点移动**（旧的挤出、新的加入）→ system+历史前缀每次从历史第一条就变 → llama.cpp/服务端前缀缓存几乎全 miss（冷 prefill 每轮 ~20-56s）
- **锚定机制**：按 provider 在会话持久化窗口锚点（`history_anchors`）——锚定后起点固定（只追加不挤旧）；超预算依次：①剔除注入消息（不进提交、零损失、不产生归档）②分层降级中段旧 tool ③仍超才归档推进锚点（前缀断一次后重新锚定，低频）
- **实测（真实大会话 + local 9B）**：前缀一致率 **48/49（98%）**；连续 run 首分片从 20-56s → **3.8-11.5s（缓存命中）**
- 快照注入仅无锚时执行（锚定后快照为推送式注入已打标跳过提交，避免锚点换算复杂化）；无锚路径行为零变化

### 云端 provider 提速降本：前缀稳定 + 历史预算（P1-9）
- 本地模型优化（P1-7 前缀稳定 / 历史预算）推广到云端：deepseek/kimi 配 `history_budget_chars: 60000` + `inject_system_notices: false`、minimax 配 `40000` + false——system 前缀静态化命中服务端 prompt 缓存（输入 token 折扣）+ 控制输入量（成本），推送式注入仍可经 architecture_status 自查（能力零损失）；超时保持全局 120s 不放大（provider 级差异由配置天然表达）
- 实测：kimi/k3-256k 默认模型端到端正常（in=5916 tokens, 回答正确）

### 默认模型支持全限定 `provider/model`（P1-8）
- `LLM_MODEL=kimi/k3-256k` 形式全限定默认模型 → 默认 client 按注册表 provider 参数装配（base_url/api_key 来自 provider 配置、模型名发送裸名，OpenAI 兼容端点不接受全限定）；裸模型名保持 env 三件套（零回归）
- 配置：`.env` 默认模型已切至 `kimi/k3-256k`（备份 `.env.bak-20260816-kimi`）

### 本地模型首 token 提速：推送式 system 注入不进提交视图（P1-7 前缀稳定）
- **根因（Stateful API 可行性验证）**：LM Studio Stateful API 增量续聊实测 TTFT 0.58s，但 OpenAI 兼容端点在**相同前缀**下同样命中引擎 KV 缓存（2.9s）——让 agent 缓存失效的真正元凶是**每轮注入的 system 消息**（[架构上报]/[预算预警]/[声明提醒]/快照，大会话已累积 181 条），下次 run 全部合并进开头 system → 前缀从第一个 token 就变 → 每轮全量冷 prefill
- **provider 级开关 `inject_system_notices`**：默认 True（零回归）；`local` 配 false → 推送式注入（架构上报/预算预警/轮数预警/声明提醒/快照/自我评估提醒）仅落会话、不进提交视图（AI 可经 architecture_status 自查，能力零损失）；功能性注入（压缩标注/降级通知/overflow 回注/轮次决策请求/故障反馈）不受影响
- **存量消息兼容**：跳过判定 = metadata 标记 + 内容前缀（[架构上报] 等）双通道，历史遗留注入消息同样生效
- **实测**：system 前缀稳定为静态文本（+压缩标注尾部），首分片从 ~70s 降至 ~25s（9B 冷 prefill 固有成本；多引擎 CPU 争抢缓解后更低）

### Web V2：全新 React 端（对齐 DeepSeek Harness Web，双版本并存）
- **独立目录 `webui/`（React 18 + TS + Vite）**，挂载 `/ui/v2` 与原版 `/` 并存（原版保留可回退）；独立分支 `feature/web-v2` 合入
- **视觉对齐**：DSH 同源设计 token（亮/暗/跟随系统，`--dsw-alias-*` 语义变量 + shiki 代码配色）、三栏布局壳、消息入场动效、移动端抽屉
- **功能对齐**：流式会话（思考块/工具链状态chip/代码块分块）、`/` 命令面板（点选即执行）、模型目录、消息反馈（👍👎 → feedback.jsonl）、会话 Markdown 导出、子代理标签、跨端同步（SSE 命名事件 + 失联自愈看门狗）
- 侧栏管理：置顶/两步确认删除/分支（fork→自动切换）/来源通道标签
- 识别链路（后端增强，原版/飞书同受益）：**auto 链**——团队识别工具（arkcli）优先 → 注册表 multimodal 模型（Kimi 实测可用）兜底 → 明确报错；docx/pdf 走 doc-extract 结构化抽取（本地提取兜底）；识别失败附件如实标注"图片未包含"防幻觉
- 新端点：`POST /api/v1/sessions/{id}/feedback`
- 文档：`docs/web-v2-diff.md`（DSH 对齐三态清单/差异对比/切换方案）

门禁：pytest 2038 passed + ruff 0 + pyright 0 + Vitest 29/29 + 分支 CI 全绿

## v0.5.6（2026-08-15）

### 修复：飞书发消息 Web 端必须手动刷新才显示（SSE 命名事件缺失）
- **根因**：SSE 规范中命名事件必须带 `event: <type>` 行；服务端只发 `data: {"type": ...}` → 浏览器按默认 `message` 事件处理，前端 `addEventListener("sessions_updated")` 永不触发（curl 能看到数据流，浏览器里却没有任何回调）
- **修复**：事件帧补 `event: connected` / `event: sessions_updated` 命名行（data 内 type 字段保留向后兼容）；新增 20s keepalive 注释行防长连接被中间层/浏览器超时掐断
- **前端加固**：失联自愈看门狗（>25s 无事件且页面可见 → 静默自愈刷新，SSE 健康时不触发）；标签页重新聚焦立即同步（后台标签页 SSE/定时器被浏览器节流时兜底）
- 测试 +6（命名帧格式 / 端点防回退守护 / 前端看门狗·聚焦·监听器静态守护）；全量 2020 passed + ruff 0 + pyright 0

## v0.5.5（2026-08-15）

### 双端统一会话 + 双向实时同步（用户需求）
- **统一会话**（已有机制确认）：owner 飞书私聊与 Web 共享同一会话（`shared_current`），Web 默认加载跨端共享当前会话；Web 新建会话同样设为共享当前
- **Web ← 飞书**（已有）：SSE `/api/v1/events` 指纹轮询，飞书侧新消息 Web 端 1.5s 内自动刷新
- **飞书 ← Web（新增）**：桥进程内 `CrossSyncWatcher` 后台线程——轮询会话目录，对映射到飞书聊天的会话（含 owner 共享当前）做增量检测，Web 侧用户输入/AI 输出**实时推送到飞书聊天**（卡片：`[跨端同步] Web 端会话「标题」新增 N 条消息`，角色标注 + 截断）
- 基线机制：桥自身回复完成后 `mark_processed` 刷新基线（不重复推送自己）；首见会话只建基线不推历史；速率受限（3s 最小间隔）多条合并；推送失败不推进基线（下轮重试，fail-open）
- `FEISHU_CROSS_SYNC=0` 关闭；测试 7 项（增量推送/自身不重推/Web 先建会话推 owner/限速合并/清理不推/损坏 fail-open/键解析）

## v0.5.4（2026-08-15）

### 显式输出预算 max_tokens（现场修复：长分析被截断、思考占大半输出只余少数）
- **根因**：请求未携带 max_tokens → 走模型默认（如 4096）；思考链模型思考占预算大半，最终分析被截断（现场：回答末尾直接中断在"（回答被截断）"，确认项都未列完）
- **修复**：`LLM_MAX_TOKENS` 默认 **8192**（env 可调）显式下发；`data/providers.json` provider 条目支持 `"max_tokens"` 覆盖（local/minimax 已设 16384）；pool 继承链路（provider 优先 → 默认 client）与客户端 payload 全链路接通
- 测试：payload 携带/缺省/配置默认/factory 装配/provider 解析与回退（+11 项）；FakeLLM 桩对齐新字段
- 配置文档补 `LLM_MAX_TOKENS` 行

## v0.5.3（2026-08-15）

### 消息响应提速：事件日志 O(n²) 续号修复（agent 通用路径，本地/云端同受益）
- **根因（用户反馈"发消息 1 分钟模型才有反应"）**：大会话（如 654 条）压缩归档时对每条消息单独写一条事件日志，而 `EventStore.append` 为求最大 seq **每次全文件扫描**——625 次连续 append 总耗时 O(n²)，实测 62s 阻塞在主循环（LLM 调用之前）；云端 80K 预算归档同样多，故本地/云端一样慢
- **修复**：seq 续号改**尾部读取**（append-only 文件最大 seq 必在尾部，反向读最后一条事件，O(1)；含损坏行容错与多段归档段取大）；`last_seq()` 同口径；`_resolve_msg_seq` 优先用 run 中内存会话（P0-5 绑定表），避免每次归档都读盘
- **实测（真实 654 消息会话 + 9B）**：run 97s → 37s，其中 LLM 固有 prefill+生成 35.7s（cProfile 实证），**agent 管线 63s → 1.3s**
- 事件日志语义零变化（seq 单调、损坏行容错、flock 并发安全、滚动兼容），相关测试全绿


### 本地大模型接入：provider 级超时（修复 LLM 请求超时 120s）
- **根因**：本地大模型（LM Studio 27B 量化实测 ~5s/千字 prefill）在 120s 全局超时内完不成首 token——40K 字上下文实测 208s 才出首字节，大上下文会话（几十万字符）必然超时报 `LLMTimeoutError: LLM 请求超时（120.0s）`
- **provider 级 `timeout_s`**：`data/providers.json` 每个 provider 可配 `"timeout_s": 600`（本地慢模型放大，云端保持全局默认零回归）；`model_catalog` 目录标注 provider 超时
- **调用语义修正**：`timeout_s` 未被 `adjust_strategy` 显式调整时，循环不再下发 per-call 覆盖，让 client 自身超时（provider 级优先、全局兜底）生效——此前 provider 配再大也会被循环的 120s 覆盖
- **配置**：`data/providers.json` 的 `local` 已配 `"timeout_s": 600`；`docs/configuration.md` 常见坑新增本地模型超时排查三步（调超时/控上下文/换轻模型）

### 本地大模型接入：provider 级历史预算（agent 发给本地模型的上下文过长问题）
- **根因（用户指出）**：agent 每轮发给本地模型的历史按全局 `HISTORY_MAX_CHARS`（80K 字符 ≈ 56K tokens）构建，本地模型 prefill 随上下文线性涨——80K 字符在 CPU 级 27B 上首 token 要 7-10 分钟，即使窗口装得下也慢得不可用；实际有用的近期内容远小于全量历史
- **provider 级 `history_budget_chars`**：`data/providers.json` 每个 provider 可配历史注入预算（字符），`_effective_history_budget` 取 min(全局, 窗口折算, provider 预算)——`local` 已配 `"history_budget_chars": 12000`（≈9K tokens），实测真实会话发送载荷 69,697 → 13,510 字符（5 倍缩小），27B 首 token 缩到 1-2 分钟、9B 10-20 秒；旧历史照常压缩归档可检索（信息零丢失，RULE-AI-00 不变）
- **`[预算预警]`/context_usage 占用率口径修正**：改为统计**实际发送载荷**（构建后消息），不再把已压缩归档的原始会话算进"当前占用"——旧口径在收紧预算后会虚高数十倍（实测 440K vs 实际 70K），误导 AI 压缩决策；`architecture_status.context_usage.breakdown` 同步如实
- **配置**：`data/providers.json` 的 `local` 已配 `"history_budget_chars": 12000`；云端 provider 不配则完全零回归

## v0.5.3（2026-08-15）

### 现场修复：代理假 IP 段（198.18/15）误拦 web_fetch（本地大模型接入用户现场）
- **背景**：Surge/Clash fake-ip 模式下代理 DNS 把目标域名解析为 198.18.0.0/15 假地址；Python `is_private` 将该段判为私网 → SSRF 防护误杀代理环境下全部外网抓取（`[内网拦截] 目标地址属于私网/保留地址段（198.18.x.x）`），既有测试被迫 `WEB_FETCH_BLOCK_PRIVATE=0` 绕过
- **修复**：全部解析地址落在 198.18/15（代理假 IP）→ 默认放行 + 回执如实标注「已按代理通道放行」；`WEB_FETCH_BLOCK_FAKE_IP=1` 恢复严格拦截；真实私网/回环/链路本地/保留段拦截语义不变（P0 不回归）；连接后对端复核（TUN 假 IP）同步放行
- **测试**：新增 `test_web_fetch_fake_ip.py`（8 项）；撤销 m48/paging/builtin 中 17 处"关拦截"绕过（修复后拦截开启下通过）
- **对端复核容错**：透明代理转发（Surge pf 重定向，对端为本机回环）放行 + logger 留痕——per-hop 预检查已把关目标，真实私网对端仍丢弃（P0-3 主体不变）；端到端实测 `example.com` 经代理通道抓取成功且回执如实标注

## v0.5.2（2026-08-15）

### 回复展示：不折叠，过长分块输出（用户需求批次）
- **Web**：回复正文折叠整体移除（消息体级 2000 字摘要折叠 + 「展开全文」按钮删除）；超长代码块（>200 行）由折叠摘要改为**顺序分段全量展示**（每段 ≤200 行、段首标注「第 i/N 段 · 共 X 行（自动分块，未折叠）」、逐段语法高亮与复制按钮保留）
- **飞书**：长回复默认**不折叠全量分段推送**（markdown 感知分段既有能力）；`FEISHU_FOLD_LONG_REPLY=1` 选择加入旧折叠行为（摘要卡 + 「展开全文」取回，命令保留向后兼容）
- 折叠实现（collapseUnit/折叠样式类）整体移除，防复活守护测试改写

## v0.5.1（2026-08-15）

### 截断信号与轮次耗尽强化（用户需求批次）
- **放大字数**：`TOOL_SUMMARY_THRESHOLD` 默认 5000 → 12000；输出分层首尾窗口 600/600 → 2500/2500——截断/摘要发生更晚、可见内容更多（硬上限 100K 安全阀不变，信息零丢失语义不变）
- **截断信号行动指引**：`[输出摘要]` 与 `[结果超长，已截断]` 回执附统一指引——继续推理前先把可见要点与待核实缺口提炼记录（推理链或 [[memory]] 记忆块），最终总结纳入；程序只发信号不替 AI 摘要（RULE-AI-00）
- **轮次耗尽决策轮**：耗尽不再直接罐装终止——注入一次 `[轮次决策请求]` 请 AI 归因：① 工具使用错误/空转 → 如实归因 + 正确做法 + 当前结论收尾；② 正常推进 → adjust_strategy 调大 max_iterations（≤500）续跑。决策轮仅一次（per-session 标志）；AI 未调大仍耗竭 → 回到罐装如实终止（程序兜底边界不变）
- **RULE-AI-11 新规则**：截断提炼与轮次耗尽自主归因写入规则真相源（`docs/ai_rules.md`）+ system prompt 嵌入（同步漂移测试覆盖）

## v0.5.0（2026-08-15）

> 安全深化 + 正确性修复批次（代码审计 18 项发现的完整闭环；审计报告与修复计划为本地过程文档不入库）。

### 安全修复（P0）
- **灾难性命令硬阻断 Guard（P0-1/审计发现 #1/#4）**：execute_command 危险命令检测重写为"全串正则层 + shlex 分段子命令层"双扫描——管道/拼接/`rm -rf` 聚合 flag/`find -delete|-exec rm`/`sh -c` 内嵌/`python -c` 载荷（rmtree/unlink/os.remove 等）此前可绕过的形态全部闭合；命中硬阻断 + 审计落盘 `data/audit/safety_blocks.jsonl`（fail-open）。模块职责如实标注为"已知模式硬阻断+审计，非完备沙箱"
- **web_fetch SSRF 重定向逐跳检查（P0-2/审计发现 #2）**：301/302 跳转此前不经私网校验（公网 URL 可跳板打内网）——curl/httpx 双路径改手工逐跳循环，每跳目的 IP 均过内网拦截，超 5 跳如实报 FAIL
- **web_fetch DNS 钉 IP（P0-3/审计发现 #3）**：解析→连接之间的 DNS 重绑定窗口闭合——curl `--resolve` 钉死已校验 IP；httpx 建连后核验对端地址（不符即断连丢弃，GET 请求行已发出的残余如实标注：保护的是回读数据）
- **会话存储跨进程写互斥（P0-4/审计发现 #5/#6）**：Session 保存此前仅进程内锁——CLI/Web/飞书多进程并存可写穿 JSON。现每会话 `<sid>.lock` flock 覆盖"读-改-写"临界区（含 load→append→save 全链），锁不可用如实降级告警
- **引擎跨会话可重入（P0-5/审计发现 #7）**：停滞指纹/overflow 计数/预算预警/快照节流等运行态此前挂在引擎单例上——同引擎多会话并发 run 互相污染（状态串台/停滞误判）。改为 `contextvars` 会话定位 + per-session 状态桶（SSE/ASGI 跨 Context 驱动用值快照还原），registry 双层线程池均做上下文传播

### 正确性修复（P1）与工程补强（P2）
- **子代理会话泄漏（P1-5/审计发现 #10）**：SubAgentRunner 执行前切到子会话但从不恢复——父级后续超长工具结果归档/变更日志归错子会话（串台）。改为 try/finally 保存并恢复注册表会话（显式字段 + `current_session_id` ContextVar 值快照还原，成功/异常/截断路径全覆盖）
- **工具超时线程/子进程泄漏（P1-5/审计发现 #11）**：`_run_with_timeout` 超时后 `with ThreadPoolExecutor` 退出会 `shutdown(wait=True)` 卡到工具自行结束（超时名存实亡），且 execute_command 的 shell 子进程不被终止。修复：超时路径 `cancel()` + 调用工具 `terminate()` 钩子 + `shutdown(wait=False)` 立即返回；execute_command 前台改 `Popen`+`communicate`（独立进程组 + `terminate()` 整树 SIGKILL），超时后 shell 及其孙进程不再残留孤儿（残余无钩子工具的工作线程如实标注：最多存活到工具自身超时/结束）
- **事件日志滚动未接线生产（P1-1/审计发现 #9）**：RotateManager 此前只有 CLI 读段清单在用，`check_and_rotate` 生产无人调用（事件日志永不滚动），且多段迁移检查在锁外有竞态、迁移后追加 seq 从 1 重启。修复：RotateManager 接线进 EventStore.append（大小触发每次查、天数触发 30s 节流）+ 会话级稳定锁 `<sid>.lock` 覆盖"检查+迁移+追加"临界区 + 多段 seq 全局续号 + 引擎 run 末 `check_rotate` 钩子（均 fail-open；未接线存储零回归）
- **fork 工具轮边界对齐（P1-6/审计发现 #15）**：fork 点切在 assistant(tool_calls) 与其回执之间 → 分支继承孤儿声明，下次运行被配对修复伪造 `[程序异常]` 回执。修复：fork 点自动向前对齐到完整工具轮边界，`ForkReport.snapped_fork_point` 如实报告实际生效点
- **tool_calls 配对漏计空 id 回执（P1-6/审计发现 #16）**：配对自检/补齐按"回执 id 非空"计数，存量会话的空 tool_call_id 回执被漏计 → 多补占位（额外 tool 消息无声明 → API 400）。修复：按 id 精确配对 + 空 id 位置兜底，自检与补齐共用同一缺口函数
- **流式断连会话漂移（P1-6/审计发现 #17）**：`run_stream` LLM 流式中客户端断连（GeneratorExit）跳过 loop 末保存 → 事件日志已追加而 session JSON 未保存。修复：部分回答如实落会话（中断标注不伪装完整）+ 事件双轨同步 + 立即保存
- **retire 指引如实化（P1-2/审计发现 #8）**：`read_path_switched` 字段名暗示已切换（实际只写切换指引）。改名 `read_path_ready_to_switch` + 新增 `switch_instructions`（READ_PATH_SOURCE 修改 + 重启两步指引），CLI 打印与回滚提示同步如实（程序不代写用户 .env）
- **providers 配置解析加固（P1-3/审计发现 #12）**：能力标志严格布尔解析（白名单字符串/非法值 warning + 回退默认，不再静默 `bool()`）；context 缺失回退 131072 与 ModelSpec 默认一致；provider/模型双层 try/except——单条非法跳过该条并如实告警，不再拖垮整个注册表
- **模型解析失败可感知（P1-4/审计发现 #13）**：`switch_model` 目标解析 ValueError 不再静默吞掉——warning 含配置模型名与失败原因；`config_status` 新增 `model_registry_resolved` 维度，AI 可感知"模型配置未生效"
- **鉴权 fail-closed + 跨站写防护（P2-1）**：`WEB_AUTH_REQUIRE=1` 未配置 `WEB_API_KEY` 旧实现静默放行（等于无鉴权）——现启动拒绝（对齐远程绑定校验语义）+ 请求期 503 如实报错；回环豁免部署的 mutating 端点新增 Origin 头校验（非回环来源 POST/PUT/DELETE/PATCH → 403，防浏览器跨站打 127.0.0.1；无 Origin 的 curl/脚本不受影响）
- **upload 体积前置检查（P2-2）**：base64 体积先查字符串长度（≈4/3 原始体积）再解码，超限直接 413——大 payload 不再先吃解码内存/CPU
- **会话锁表无界增长 + 首聊竞态（P2-3）**：`session_locks` 改 LRU 上限 1024（淘汰最旧空闲锁，持锁不淘汰防互斥失效）；无 session_id 并发首聊的"取共享→建会话→设共享"收进同一模块级 guard——不再双建孤儿会话
- **LLM 连接泄漏（P2-4）**：`LLMClient.close()` 此前无人调用。新增 `ModelClientPool.close()`（default+缓存全关，幂等）与 `LoopEngine.close()`；`clear_cache()` 热重载路径改为先关旧 client 再清空；CLI 主返回路径、web 退出、飞书停机均接线关闭
- **eval 管道验证补强（P2-5）**：wilson_ci docstring 漂移修复（k=0 正常计算真实区间如 (0.0, 0.562]，仅 n≤0/k<0 返回 (0,0)）；dry 模式新增注入可见性自检（真实状态追踪器注入 FAILURE → architecture_status 快照路径断言可见，不可见即管道失效如实报错）
- **fallback 引擎级集成测试（P2-6）**：真实 `_try_fallback_chain` 触发路径（主模型 500 → 降级链成功）——断言回答来自降级模型、`[模型降级]` 回执注入、architecture_status 降级态与 `model_fallbacks_count` 配置计数可见；4xx 不降级与链全失败汇总两条零回归路径同测

## v0.4.0（2026-08-15）

### 新能力
- **孤儿 tool_calls 合成回执（HARNESS-01）**：`run_stream` 客户端中断（close）时自动写「已取消」合成回执并立即保存——不再产生「有声明无回执」的孤儿声明（严格 FC 协议 400 根源），对账不变量「声明数 = 结果数 + 取消数」
- **`request.meta` 事件（HARNESS-02）**：每轮 LLM 请求快照入事件日志（round/model/thinking/reasoning_effort/tools_count/history_chars/budget），回放可确知"当时用的哪个模型/挂了哪些工具/预算多少"
- **web_fetch SSRF 内网拦截（HARNESS-03）**：`WEB_FETCH_BLOCK_PRIVATE`（默认开）拦截私网/环回/链路本地/保留段地址（IP 字面量 + DNS 解析双路径），命中返回 BLOCKED `[内网拦截]`——防云元数据（169.254.169.254）等内网探测
- **上下文预算预警（HARNESS-04）**：上下文占用率 ≥80% 预算时注入一次 `[预算预警]`（含占用率/字符数），"压缩/收尾"决策归 AI——程序不自动压缩（RULE-AI-00）
- **程序故障指标（R2/A6）**：`architecture_status` 上报程序故障计数（event_write/memory/llm_call/session_persist 等 fail-open 点），AI 可感知"程序故障率"并应对
- **archive-index 存量段索引重建（R3）**：`archive-index` 命令幂等重建历史段检索索引（存量无索引段全文扫描兜底升级为索引检索）
- **飞书显示批次**：超长行零宽空格折行（fence 内不折）+ 分段字节预算（50000→30000 防物理上限）+ 表格降级增强（来源标注/列数提示）+ 摘要卡交互化（「展开全文」命令，消息条数收敛）+ 状态卡 1s 节流 + 发送最小间隔 300ms + 渲染支持矩阵 `docs/feishu_render_matrix.md`
- **本地真实回归脚本**：`scripts/run_real_smoke.sh`（冒烟 + 评测集，key 从 env/.env 读取，`--quick` 模式）——key 不上传策略下的 CI 补位

### 改进
- **工具重名去噪（R1）**：同一对象重复注册静默跳过（修复 `RUN_MODE=minimal` 过滤失效），工具面更干净
- **评测 token 开销指标（A2）**：场景级 tokens_in/tokens_out 聚合 + 报告渲染（`scripts/run_eval.py`）
- **run_mode 文档化（A1）**：`docs/configuration.md` 补 standard/ptc/minimal/creative 模式说明
- **开发方法论公开（B10）**：`docs/development_methodology.md`（SoT 先行/如实记录/零回归/评测纪律）

### 修复
- **上报冷却首调误拦截（HARNESS-05）**：`EventReporter.should_report` 首次调用 last 取 0.0、`time.monotonic()` 从系统启动起算——CI 全新 runner 启动 <60s 时首次上报被误判"冷却中"拒绝，致自我评估/演进提醒偶发不注入（本地系统启动久无法复现，CI 复现；回归测试模拟系统启动 5s 场景）
- **CI nightly 无 key 跳过失效**：`exit 0` 只放行当前 step，后续 real_llm/评测 steps 无 key 时仍执行致 exit 2——改为 GITHUB_OUTPUT 条件门（workflow_dispatch 实测修复）

### 文档
- 飞书渲染支持矩阵（`docs/feishu_render_matrix.md`）+ 开发方法论（`docs/development_methodology.md`）

### 框架化批次（2026-08-15 追加）
- **headless 服务模式（B5）**：`examples/04_headless_service.py`（无 UI 纯 API 嵌入——`build_engine` 单实例 + 同步/流式对话端点约 20 行）
- **LLM 错误注入矩阵（A4）**：网络/超时/HTTP 4xx/HTTP 5xx/协议五类错误各注入引擎循环，断言 `[LLM 调用异常]` 三件套如实呈现 + 类型名不吞并 + 不抛穿
- **发布节奏制度化（B11）**：Release Drafter（PR 标题自动归类 changelog 草稿）+ tag 触发门禁复核 + Release 草稿生成 + CONTRIBUTING 发布流程
- **多 provider 成本路由增强（B6）**：`switch_model` 成功回执注入目标模型成本档 + 能力语义 + 上下文窗口（元数据缺失如实标注，判断归 AI）
- **插件化 Skill 可演示化（B3）**：仓库自带示例技能（`skills/`）入库，真实装配端到端测试
- **评测集贡献指南（B7）**：`docs/eval_scenarios.md`（schema + 判定注册 + 30 分钟新增路径 + PR 验收）
- **API 契约稳定化（B5）**：公共签名快照测试（build_engine/LoopEngine/SessionStore/ToolRegistry 参数锁定）+ api.md §1 装配链路可执行验证

## v0.3.0（2026-08-14）

### 新能力
- **插件化 Skill 加载**：`skills/<name>/SKILL.md` 目录自动扫描，AI 经 `skill_list`/`skill_load` 发现并加载外部技能执行（`SKILLS_DIR`，默认 `./skills`）——外部扩展零代码
- **动作状态条（H-UI）**：引擎动作观察者（thinking/tool_call/tool_result/answer/done 事件）+ 飞书状态卡实时更新（💭 思考中 / 🔧 正在调用工具 / ✅ 完成 / ✍️ 生成回答）；Web 流式本就支持（思考 + 工具进度链）
- **人工审批流**：EXEC_MODE 拦截项可在 CLI 交互模式终端确认（`set_approval_callback`，无终端 fail-closed 拒绝），审批审计落盘
- **symlink 写防护**：edit_file 写路径含符号链接拒绝（防越界写）；read_file 读 symlink 如实标注
- **评测体系**：固定评测集（6 场景）+ 运行器（`scripts/run_eval.py`，真实 LLM / `--dry`），Wilson CI 统计约束，CI nightly 自动运行
- **`LoopEngine.run_single`**：一次性便捷入口（自动建会话）

### 改进
- `LLM_MAX_ITERATIONS` 默认 20 → **40**（多步任务不再轻易触顶）；达 80% 注入 `[轮数预警]`，AI 可经 adjust_strategy 调大（硬上限 500）
- `HISTORY_MAX_CHARS` 默认收敛统一为 **100K**（1M 曾致上下文撑爆）
- 档案分片 + sidecar 检索索引（100MB 开新段，检索跨段最近优先，存量无索引全文扫描兜底）
- 飞书心跳历史轮转（`FEISHU_HEARTBEAT_HISTORY_MAX_MB`）
- HashEmbedder v2（2+3-gram）+ embedding 缓存版本化
- `model_catalog` 选型指引（成本/能力语义 + switch_model 引导）
- CI：GitHub Actions 三件套门禁（pytest/ruff/pyright）+ nightly 真实评测

### 文档
- 公共 API 参考（`docs/api.md`，含稳定 API 声明）+ 3 个示例（`examples/`）
- 配置参考（`docs/configuration.md`，分组配置表 + 常见坑速查）
- 事件溯源设计（`docs/event_sourcing.md`）+ 评测集扩展指南（`tests/eval_sets/README.md`）
- 英文 README（`README.en.md`）+ 贡献指南（`CONTRIBUTING.md`）

### 修复
- `maybe_trigger` 首次触发平台 bug（容器 monotonic 从 0 开始误判冷却，提取静默失效）
- pyright 1.1.411 兼容（divider 类型）、CI 环境兼容（测试自足）

## v0.2.0（2026-08-14）

- D1 事件溯源单一真相源（5 类事件 + 回放/对账/迁移/回滚/退役/会话 fork/过滤钩子）
- 实时停滞检测（连续同指纹 3 提醒 / 5 熔断）+ edit_file 换行归一化 + mtime 基线防并发
- 开源发布（Apache-2.0 + 公开面精简）
