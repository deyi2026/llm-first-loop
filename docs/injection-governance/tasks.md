# 注入治理专项任务图（INJECTION-GOVERNANCE）

> 立项: GOAL-20260829-afd095ab | 2026-08-31 | 状态: **R0-R8 PASS；R8.4 Eligibility AUDIT PASS；R8.5 resolved-episode PASS；R8.6 Tool Eligibility AUDIT PASS；R8.7 Tool Eligibility PASS；R8.8 seven-blocker closure PASS（eligibility gate READY）；behavior canary / R9 未开始**
> 依赖链: R0 → R1 → {R2, R3, R4, R5, R6 并行} → R7 → R8 shadow/soak → **R8.4 audit → R8.5 resolved-episode retirement → R8.6 tool eligibility/recovery audit → R8.7 dynamic tool eligibility/recovery → R8.8 remaining eligibility blockers** → behavior canary → R9。R0 未过数据门不得进入行为实现；R8.8 full fixed-point 未过不得进入 behavior canary。

## R0 基线取证与 fixture 建立（数据门）— ✅ PASS
- 内容: 用真实 `data/event_logs` 重建 human turn，区分 user truth / user-role program appendix / system notice；量化尾后注入、会话级重复、资料祈使污染、provider wire 连续 user；按 model/compact/recovery 分桶；冻结脱敏结构 fixture。
- 产物:
  - `scripts/analysis_injection_baseline.py`
  - `docs/injection-governance/r0/baseline.jsonl`
  - `docs/injection-governance/r0/baseline-manifest.json`
  - `docs/injection-governance/r0/report.md`
  - `docs/injection-governance/r0/fixtures/structural-fixtures.json`
  - `tests/unit/test_injection_baseline_analysis.py`
- 验收: R0-1~R0-4 全 PASS；origin coverage ≥95%；request attribution ≥95%；四类结构 fixture 可确定性复现；不调用 LLM。
- 说明: 既有 cognilocal 随机行为复测不属于 R0 硬门；用户此前已取消重复基线跑，行为 A/B 统一留到 R7/L3。
- evidence_required: true

## R1 L1 语义边界落地 — ✅ PASS
- 内容: `injection_labels.py` 单一真相源；四层标记；每个 program appendix 最多一条冲突仲裁声明；资料块去祈使句。
- 产物: `src/llm_loop/core/injection_labels.py`、`tests/unit/test_injection_labels.py`、`docs/injection-governance/r1/report.md`，并迁移 memory/experience/archive/hotcard/digest/model-switch/declaration/recovery/status/build 聚合链。
- 验收: 核心 program-user 全部带 canonical origin metadata；production enforce 夹具仲裁声明计数=1；REFERENCE command-shaped 历史改为中性占位+ref；focused 147 tests PASS；R0 frozen diff=0。
- 说明: R1 只完成来源/语义边界，不宣称消除 R0 的尾后注入、重复或 wire 违规；这些属于 R2-R7。
- evidence_required: true

## R2 注入预算硬上限（L2-1）— ✅ PASS
- 内容: `INJECTION_BUDGET_CHARS` 候选值 + 统一优先级丢弃 + 非祈使回执；在统一 assembler 门闸实现，不能各注入源各算一套。
- 产物: `src/llm_loop/core/injection_budget.py`、`tests/unit/test_injection_budget.py`、`docs/injection-governance/r2/report.md`；`config.py` / `.env.example` 接入候选参数，`build.py` 只消费中央 budget plan。
- 验收: persisted/dynamic/header 三类 program-origin 同一门闸；超限整块丢弃、不截断半块；accounting `used_chars <= budget`；off/shadow/enforce 多预算矩阵实际 wire 均低于 accounting；非祈使 receipt 同预算计费；8000 明示仅候选。
- 说明: `COG_RUNTIME_PACKET_BUDGET` 保留为 Cognitive packet 内部投影压缩预算，只能进一步减少 packet；跨来源最终硬上限的 SoT 是 R2 `INJECTION_BUDGET_CHARS`。R3 已在其外层约束下完成资料降密。
- evidence_required: true

## R3 资料按需化 + 指针化 + 会话级去重（L2-2）— ✅ PASS
- 内容: `REFERENCE_AUTO_TURNS` 候选 K + 显式任务切换门；每帧 ≤2 行（事实 + ref）；stable ref 优先/hash fallback；seen-set 从持久 message metadata 重建，跨 compact 保持。
- 产物: `src/llm_loop/core/reference_injection.py`、`tests/unit/test_reference_injection_{policy,integration}.py`、`docs/injection-governance/r3/report.md`；memory/experience/skill/digest/compact/hotcard 自动表示迁移到 pointer-era。
- 验收: K+1 后 memory 自动检索即停止；09c44093 x18 stable-ref trap 完整正文仅 1 次；显式 task switch 时 seen ref 最多 1 行、新 ref ≤2 行；compact 不再回灌 key facts/index/snippets；主动 `search_records/search_archive` 不回归；原 R3 237 focused tests PASS；post-R3 adversarial audit 进一步验证 human-ref poisoning=0、memory/experience/digest ref 可精确水合、session scope 与真实 restart，并以 281/281 扩展回归 PASS；R2 15 点预算矩阵 PASS；R0 frozen diff=0。
- 说明: K=3 仍为候选；seen-set 不新增 Session 顶层状态，而从 durable metadata 重建。hotcard 只改成两行 file pointer，消费/恢复语义留 R4。
- evidence_required: true

## R4 程序恢复边界（L2-4）— ✅ PASS
- 内容: auto_continue 收敛为 closed `ProgramRecoveryAction` + `[任务·程序恢复]` canonical template；可执行 recovery 不再持久化为 session Message，而是 per-session `_RunState` one-shot slot，next-build 消费后清空；旧 persisted recovery 仅从 provider view 退休，storage/event truth 不删。
- 审计: 新增 `program.recovery` session event，记录 action/trigger/turn_ref/scope；可审计事实与可执行 prompt 生命周期分离。
- 验收: 143/143 focused、458/458 expanded PASS；A/B session 并发隔离；真实 1210 E2E 第二 payload 恰好一个 recovery、后续用户轮为 0；R2×R4×R6 15 点全 PASS；R0 frozen 0-byte；pyright 0/0。
- 说明: R4 不实施 R5 identity stripping、R7 A/B、R8 model tiering。
- evidence: `docs/injection-governance/r4/report.md`
- evidence_required: true

## R5 身份问答剥离（L2-3）— ✅ PASS
- 内容: sequence-aware identity/self-description episode 只治理长期 summary/index projection；ArchiveStore raw content/reasoning 与 Session trim backup 原样保留。identity 起点用 `[身份问答 x N 轮，已略——本会话主体任务见下]`，episode 后续详情不进 summary。
- 实现: `core/identity_summary.py` 保守 classifier + genuine-human episode boundary；`_archive_sink` 对新 identity archive 写 `summary_source=identity_filtered` 并跳过 LLM backfill；`search_archive(with_summary=true)` 不得从 raw preview 二次摘要；legacy Session trim 多轮 identity 聚合成单行 xN。`fixed_summary/summary_chain` 保持 inert。
- 验收: 97/97 focused、542/542 expanded PASS；冻结三问题会话各命中 1 个纯 identity opener，clean-control 69715765 的 102 个 genuine-human turn identity hit=0；mixed `你现在是什么模型？上一轮我让你记了什么？` 保留；R2×R4×R5×R6 15/15；R0 frozen 0-byte；pyright 0/0。
- 说明: pre-R5 archive 不做破坏性迁移；R3 已阻止其自动 prompt 回灌。R5 不进入 R7/R8/R9。
- evidence: `docs/injection-governance/r5/report.md`
- evidence_required: true

## R6 用户原话尾位 + wire invariant（L2 横切）— ✅ PASS
- 内容: provider-view 出口统一 `program appendix → fixed separator → exact user truth` 单 user envelope；Session/event history 不改序；仅 initial human-ingress 投影，tool-followup 不重放 truth。
- 产物: `src/llm_loop/core/user_truth_wire.py`、`tests/unit/test_user_truth_wire.py`、`docs/injection-governance/r6/report.md`；`history.py` 只在 initial ingress 保护 current human exact；`err1210.py` 新增 USER_ENVELOPE 安全 strip/defer。
- 验收: 413/413 扩展回归 PASS；off/shadow/enforce×5 budget 共15点均 `generated<=used<=budget` 且 `tail_user_run=1`；compact 后 exact truth 仍尾位；oversized current user 不再被 surrogate 替换；1210 retry 保留 exact user；R0 frozen 0-byte diff；pyright 0/0。
- 说明: R6 不改变 R4 recovery 动作策略、R5 identity stripping、R7 A/B 或 R8 model tiering。
- evidence_required: true
- evidence_required: true

## R7 L3 A/B 验证 — ✅ PASS（exact cognilocal 覆盖 N/A）
- 内容: 冻结 R0 结构失败形态 A 臂 vs 当前 R2/R3/R5/R6 production helper B 臂；6 个无工具 synthetic fixture 覆盖 identity-header、command-conflict、repetition、injection-pressure 与 critical memory-dependency；同模型/temperature=0/seed=42/max_tokens=256。
- 模型: `qwen3.8-27b-mlx@4bit` 弱变体 + `qwen/qwen3.8-27b` 同系列对照；原指定 `cognilocal/qwen3.8-27b-cog` 在 8901 本轮未提供，明确记 N/A，不做别名替代。
- 验收: MLX B 完成率 100%、漂移 0%、用户支配率 100%、平均注入占比 16.44%、结构硬门全 PASS；A 完成 66.67%、支配率 0%、注入 32.57%、结构 FAIL。GGUF control A/B 均 100% 完成，但仅 B 结构 PASS，且注入降至 16.44%。
- 校准: K=0/1 均丢 critical T6，K=3 PASS → 保留 K=3；budget 512 丢 T6，900/2000/8000 PASS → 900 仅为本 fixture 最小通过候选，R7 不修改生产默认 8000。
- evidence: `docs/injection-governance/r7/report.md`、`r7/results-mlx4bit.json`、`r7/results-qwen27b.json`。
- evidence_required: true

## R8 按模型能力分档（L2-5，后置 shadow）— ✅ PASS（R8.3 SOAK PASS；behavior canary NOT STARTED）
- 内容: 只读取当前路由绑定的 ProviderRegistry/ModelSpec；`weak/unknown -> minimal`，`strong+reasoning=false -> standard`，`strong+reasoning=true -> full`。第一阶段固定 `mode=shadow, applied=false`，不改变 prompt。
- 归因: 新增独立 `injection.profile.shadow` event；primary / fallback / err1210 retry 逐真实 provider attempt 记录，避免 request.meta 的 round 级模型快照误归因 fallback。
- 零行为证据: capability-only minimal↔full 对照的实际 `messages+tools` byte-identical；R2×R4×R5×R6 15/15；R0 frozen 0-byte；focused 268/268；pyright 0/0。
- runtime inventory: R8 初验为 11/11 unknown、覆盖 0%；Post-R8 R8.1 只对有受控证据的模型补 metadata；owner 随后退役不用的 Qwen3.6，R8.2 远端受控 A/B 后，mxnook 持续 HTTP 502，且 owner 明确表示可忽略，现已从 active inventory 退役；当前 active inventory 为 9/9 已分类（strong=1、weak=8、unknown=0，覆盖 100.0%，full=1/minimal=8），`canary_ready=true`。这只表示 metadata gate READY，behavior canary 尚未启动。Git-ignored providers.json 已做 metadata-only 更新，但未调用 refresh_config；不把剩余缺元数据伪装成弱/强。
- R8.3 soak: mirror live registry 9/9；strong/weak/40-message long-history 共 7 个真实 primary attempts，7/7 profile events，unattributed=0、churn=0、violations=0，全部 shadow/applied=false；fallback/err1210/byte-identity 3/3；focused 145/145；R0 0-byte。
- evidence: `docs/injection-governance/r8/report.md`、`docs/injection-governance/r8/shadow-inventory.json`、`docs/injection-governance/r8/capability-audit.md`、`docs/injection-governance/r8/soak-gates.md`、`docs/injection-governance/r8/soak-report.md`、`docs/injection-governance/r8/soak-evidence.json`。
- evidence_required: true

## R8.4 Prompt Eligibility Audit — ✅ PASS
- Owner principle: **resolved is retrievable, not injectable**。已解决问题/任务的 user+assistant+tool+reasoning 退出自动 working context，只保留可检索 index/archive；真正 follow-up 再按 ref hydrate。
- 审计状态语义: DONE=provider prompt 已排除；PARTIAL=已降密/去重/ref 化但仍自动可见；OPEN=缺生命周期门或仍有 stale/observability 注入。不得把 PARTIAL 写成“已经不注入”。
- P0 发现: resolved episode 尚无 provider-view retirement；非 compact resolved history 还缺完整检索索引；model_switch_notice 复制最近 user/assistant 并持久化继续命令；declaration_reminder 在 final 后写 role=user；Evidence Recovery Manifest 当前 enforce 且每 build user-tail/R2 旁路；future Cognitive packet 扫全部 memory_snapshot；local 每轮固定 command-shaped behavior hint；unknown slot fail-open STATUS；round-exhaustion consumed prefix 在 R1 wrapper 后机械复现失效。
- 运行只读取证: active 62 sessions / 11061 messages；storage 中 memory_snapshot=382、experience_tip=118、model_switch_notice=21、session_digest_catalog=5、declaration_reminder=3；这些是存在性证据，不冒充 provider-wire 计数。
- 产物: `docs/injection-governance/eligibility/audit.md`、`docs/injection-governance/eligibility/matrix.json`，并同步 design/requirements/tasks。
- 边界: R8.4 本身只审计、不改 `src/`；后续实现必须逐项回写同一 matrix，不另起第二套状态口径。
- evidence_required: true

## R8.5 Resolved Episode durable index + retirement — ✅ PASS（new/proven；legacy migration NOT STARTED）
- Durable first: 新增 append-only `EpisodeStore`（`data/episodes/<sid>.jsonl`）；stable `episode:` ref；同 ref 幂等、冲突 fail-closed；`flush+fsync` 成功后才允许 `resolved_episode_ref` 标记，写失败不退休。
- Resolution proof: 仅 `answer_origin=model + run_end_reason=completed + final非空 + resp.truncated=false` 才写 `episode_resolution_candidate=true`。pre-R8.5 history 无 proof 不猜 resolved。
- Provider retirement: 下一 build 在 history/budget/profile 前过滤 resolved ref；storage/event truth 不删。Cognitive packet 的 persisted memory scan 同样跳过 resolved ref，防第二路径复活。
- Retrieval: 复用 `search_records(kind=episode)`；query 空列最近 ref、关键词搜索、`episode:...` 精确 hydrate、`#offset=N` 分页；不新增 tool，不新增 ref/offset/max_chars schema 参数。
- Protocol/cache: original↔filtered history anchor 双向映射；专项 E2E 验证旧 episode 退休后新 turn 的 user + assistant(tool_calls) + tool pairing 完整。provider-visible char 统计也排除已退休内容。
- Durable-user protect: 明确“以后/始终/永远/不要再/from now on/always use/never use”等 standing instruction 保留 exact genuine user 原文；同轮 answer/tool 仍退休。完整 effective-state/supersession 尚未实现，E06 保持 PARTIAL。
- Hydration boundary: EpisodeStore 保存 genuine user + visible assistant/tool evidence；不复制 program-only prompt material 和 private `reasoning_content`。
- 验证: `tests/unit/test_resolved_episode.py` 13/13；history/cache/tool-round/1210/R1-R8/introspection/factory adjacent suite **420/420 PASS**；changed paths pyright 0/0；R0 四门 PASS 且 r0 directory hash before/after 均 `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a`。
- Remaining blockers: legacy resolved migration proof、model_switch 当前轮复制、Evidence Manifest R2 bypass、legacy/unresolved packet memory、local dynamic hint、unknown producer fail-open、round-exhaustion consumed mismatch。behavior canary 继续 NOT STARTED。
- evidence: `docs/injection-governance/eligibility/resolved-episode-report.md`、`eligibility/matrix.json`、`tests/unit/test_resolved_episode.py`。
- evidence_required: true

## R8.6 Tool Eligibility + Recovery Audit — ✅ AUDIT PASS（implementation NOT STARTED）
- Owner principle: **available is discoverable, not necessarily injectable**。ToolRegistry 存在不等于每轮 provider prompt 都应携带该 schema。
- Baseline: current runtime config + detached clean-source registry build=61；cloud lazy tool-array=22,692 chars；full tool-array=39,295 chars。建议 universal CORE=9 / 3,418 chars（-84.9%），其它工具按任务/状态 discovery。
- Classification: CORE=9、DISCOVERABLE=49、DEGRADED=1 (`web_fetch`)、QUARANTINED=2 (`playwright_exec`, `playwright_test`)；当前 Playwright Python 包和 chromium 均缺失。
- MCP: `.env` 当前仅 1 个 dsh server；stdio initialize+tools/list 可用但 tools=0，因此 active MCP capability=0，建议 quarantine/disable；historical `mcp_dsh_write` 当前不在 registry，历史 0/3 均 sandbox-readonly，应维持 retired。
- Recovery: 已冻结 proposed 16-rule failure/context policy。`web_fetch` 作为标杆：Toutiao/anti-bot/JS-shell 走 `web-fetch-fast`，404 先找 canonical URL，timeout/5xx 才 bounded retry，security block 不建议关安全策略。
- Skill health: `web-fetch-fast` 静态文档的 Chromium fallback 当前 runtime 不可执行；后续 routing 必须把 Skill 与 runtime health 取交集。
- 产物: `docs/injection-governance/tool-eligibility/audit.md`、`matrix.json`、`recovery-policy.json`、`web-fetch-case.md`；Prompt Eligibility `E31 tool_schemas` 同步记录本审计证据。
- 边界: 本阶段 docs/audit only；**不改 src、不改 registry.schemas/local allowlist/MCP 配置、不启动 behavior canary/R9**。
- 下一实现门: deterministic dynamic tool projection + runtime health + typed recovery + discovery fixtures；验收 default cloud schema <=5K、default tools <=12、hidden-needed discovery=100%、deterministic retry=0、R0 diff=0。
- evidence_required: true

## R8.7 Dynamic Tool Eligibility + Runtime Health + Typed Recovery — ✅ PASS
- Projection: `TOOL_ELIGIBILITY_MODE=enforce` 默认对 local/cloud 统一应用 stable CORE9 + current user task + active tool protocol + latest typed-recovery-next；`shadow/off` 保留旧 provider surface。
- Discovery: 复用现有 `get_tool_schema(tool_name)`；`*` 列目录、`?keyword` 搜索、exact name 取完整 schema，不新增工具/参数。
- Runtime health: Playwright Python prerequisite 缺失时 `playwright_exec/test` 不投影，stale direct call 亦被 registry 拒绝并给 replacement；MCP `tools/list=0` 时立即关闭连接并保持 0 capability。
- Typed recovery exemplar: `web_fetch` Toutiao preflight 不执行 generic network call，直接给 `web-fetch-fast`；403/418/404/429/JS-shell/timeout+5xx/security-block 分类决定 retry/replacement。匹配 typed policy 时不再追加 generic/experience 冲突建议。
- Clean-source pre-commit evidence: registry61；all lazy22,699/full39,303 chars；simple CORE9 raw3,425 / provider-wrapper3,714（-84.9%）；ordinary URL=10 tools raw3,863；schedule=10 tools raw3,866；browser intent 因 Playwright quarantine 仍9 tools。
- Verification: detached clean R8.7+MCP+schema focused **34/34**；R1-R8.5/history/tool/fallback/1210/Evidence/factory/MCP/web adjacent **572/572 PASS**；pyright 0/0；py_compile PASS；R0 四门 + frozen hash byte-identical；22-file security/staging boundary PASS；clean status before/after clean。
- Existing debt (not R8.7 regression): `test_config.py::test_load_settings_full` 在 base e1e7a12 已错误期待 `./data`；`test_loop_mixin_split.py::test_complexity_reduction` base engine 1276 已超过旧1172阈值；本轮不改这两个无关债务。
- Remaining: R8.6 其余非-web-fetch recovery rules 仍 PROPOSED；Prompt Eligibility 其它7 blockers 未清；behavior canary/R9 继续 NOT STARTED。
- Live activation: 本阶段未重启 mirror；标准 restart 脚本强制从当前 worktree `src/` 启动，而工作区仍有任务前 unrelated Cognitive/scheduler/web 源码脏改动。为保持因果隔离，不用 stash/临时替换源码冒险重启；待这些 dirty source 独立收口后再 controlled reload。
- evidence: `docs/injection-governance/tool-eligibility/r87-report.md`、`matrix.json`、`recovery-policy.json`、`tests/unit/test_tool_eligibility_r87.py`。
- evidence_required: true

## R8.8 Prompt Eligibility 七 blocker closure — ✅ PASS（eligibility gate READY；behavior canary NOT STARTED）
- Legacy episode: pre-R8.5 仅用 durable event `message.appended ↔ run.end(completed, not truncated, preview match)` 唯一证明迁移；当前只读 census 136/182 可证，46 fail-open 保留，不做猜测式批量 mutation。
- Memory: persisted `memory_snapshot` 只有 exact current `turn_ref` 自动可见；old/legacy/unbound 同时退出 flat provider + Cognitive packet，但 durable retrieval 不删。
- Model switch: 零 prompt，仅 `model.switch` observability；不复制 recent chat / 不下达 program continue。
- Evidence: Recovery Manifest 不再每 build 自动注入、关闭 R2 bypass；新增 `list_evidence(scope=recovery)` 作为显式 bounded queryless discovery，read/search/source-reuse 继续。
- Local/unknown: 删除 local command-shaped behavior patch；新增 dynamic producer explicit allowlist，unknown deny-before-profile/budget + telemetry。
- Round exhaustion: 按 metadata identity consume，并在 `session.save` 前持久化 consumed，防 reload resurrection。
- Focused/adjacent: 112/112 PASS；Evidence Phase4/5/7 31/31；touched pyright 0/0；R0 四门 PASS + frozen hash byte-identical。
- Repo-wide unit audit: 正确 `.venv` 可完整 collection；已见 rules/P0-prefix/hotcard failures 在 a5bd89c baseline 同红，config/engine-size 是 R8.7 已知 debt；context-warning full-suite order-dependent 红灯在 isolated 当前代码 2/2 PASS（ratio=0.869）。不为 unrelated debt 修改代码。
- Gate: implementation commit `b6050d3` detached-clean fixed-point PASS 后，`behavior_canary_allowed=true` / `behavior_canary_gate_state=READY`；这只放行下一阶段审批，本阶段未启动 behavior canary/R9。
- evidence: `docs/injection-governance/eligibility/r88-report.md`、`eligibility/matrix.json`、`tests/unit/test_prompt_eligibility_r88.py`。
- evidence_required: true

## R9 主区应用与收口
- 内容: 镜像实现与 A/B 证据提交用户审批 → 主区应用 → 重启 → 运行观察。
- 验收: 用户批准记录；主区应用后无新增注入结构违规；目标收口。
- evidence_required: true

## 风险登记
- stable prompt/标签变更可能导致一次前缀缓存冷启动；集中一次变更，之后保持字节稳定。
- 资料按需化可能损失“无意识相关性”；以任务切换检测 + 主动检索补偿。
- user truth 尾位不得通过新增第二条 user 实现，必须服从 provider wire contract。
- REASONING_TAIL 思维链回传不并入本专项。

## R8.9 Ephemeral Control Lifecycle — ✅ PASS
- Root cause: same-human-turn control state was persisted as ordinary session history and therefore regained prompt authority on later human turns; declaration/fallback notices were generated after the response they allegedly guided.
- E14: declaration discrepancy => LoopResult/UI + validator audit/action only; no prompt-history append; legacy exact fixed sentence safely retired.
- E15/E16/E17: stagnation, empty-search, overflow => `prompt_lifecycle=current_turn` + exact `turn_ref`; same turn visible, next turn denied; legacy system frames denied centrally.
- E27: post-fallback notice => no session prompt append; status/audit/action remains; all-failed detail goes to current program final result.
- Verification so far: production pyright 0/0; clean/new test pyright 0/0; focused+adjacent 22-file suite PASS; history/reference 77/77 PASS.
- Fixed-point: implementation commit `9c208df` detached clean PASS; production pyright 0/0; clean/new test pyright 0/0; 22-file focused+adjacent suite PASS; R0 four gates PASS; frozen hash unchanged. No behavior canary/R9 start.

## R8.10 Program-final + Program Fault Authority Closure — ✅ PASS
- Owner rule: **program state is observable/retrievable, not self-injecting**；storage/event truth、current-user disclosure、provider protocol shape 与 prompt authority 分离。
- Program-final: 历史 `answer_origin=program` assistant 不再把完整错误/取消/守卫/停滞正文自动回灌 provider；只保留 byte-stable assistant 边界 `[程序终止边界·无模型回答]`，并移除 reasoning。真实 census=52 条/22 sessions，8,251 chars → 728 chars，动态历史减少 **91.18%**，同时保持 user→assistant→user 结构，避免重新制造 consecutive-user/1210。
- E33: `session_persistence` / `archive_sink` / memory retrieval fault 继续保留 recovery、selfheal_log、program-fault status、action telemetry，但不再写 session/system prompt 或 memory_snapshot；legacy system `[程序异常]` provider view 中央退役。loop-end save failure仍向当前用户如实提示，下一 turn 由 program-final 固定边界降密。
- 验证: implementation commit `7b5334d` detached clean；focused **105/105 PASS**；broader adjacent **274/274 PASS**；production pyright **0/0**；R0-1~R0-4 PASS，frozen hash `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a` 不变；checkout before/after clean。
- Matrix: E33 PARTIAL→DONE；总计 `DONE=20 / KEEP=1 / PARTIAL=10 / OPEN=3`。`behavior_canary_gate_state=READY` 保持，但 behavior canary / R9 **未启动**。
- evidence: `docs/injection-governance/eligibility/r810-report.md`、`eligibility/matrix.json`、`tests/unit/test_p0b_program_feedback.py`、`tests/unit/test_loop_honest_feedback.py`、`tests/unit/test_memory_turn_snapshot.py`、`tests/integration/test_fault_isolation.py`。
- evidence_required: true

## R8.11 Observability Receipt Prompt Exit — ✅ PASS
- E20 `cache_gate_note`: cache gate runtime intervention remains, but `gate_note_pending` is consumed as observability-only state; action trace records `prompt_chars=0`; live producer removed from prompt allowlist; legacy err1210 restore/parser support retained without provider replay。
- E21 `injection_budget_receipt`: pruning receipt remains in `InjectionBudgetResult.receipt_content` and `action.injection_budget` telemetry only; no synthetic receipt BudgetBlock, no budget reservation/charge, no post-eligibility wire/packet append；`used_chars` now measures actual kept prompt material。
- morphology: armed gate marker no longer changes provider wire/golden digest；engine-level 1210 recovery fixtures use live interop slot rather than retired gate-note producer。
- 验证: implementation commit `1114044` detached clean；focused **108/108 PASS**；broader **242/242 PASS**；production pyright **0/0**；R0-1~R0-4 PASS；frozen hash `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a` 不变；checkout before/after clean；生产 ruff findings 与父提交基线一致，无新增 lint debt。
- 工作区隔离: `tests/integration/test_cognitive_integration.py` 的并行 import-order/newline diff 未纳入本批；仅 R8.11 四条行为断言通过 index-only partial staging 提交。
- Matrix: E20/E21 OPEN→DONE；总计 `DONE=22 / KEEP=1 / PARTIAL=10 / OPEN=1(E25)`；behavior canary 仍只 READY，未启动。
- evidence: `docs/injection-governance/eligibility/r811-report.md`、`eligibility/matrix.json`、`tests/unit/test_injection_budget.py`、`tests/unit/test_injection_fingerprint.py`、`tests/integration/test_cognitive_integration.py`。
- evidence_required: true

## R8.12 Interop Notify / Backlog Prompt Exit — ✅ PASS
- E25 `interop_notify_and_backlog`: `topic=notify` 首见/重复均不再构造 Message；直接归档 `done/`，正文/ref/source/id 保留给 Web interop UI/retrieval，结构化 `interop.notify` action 标注 `prompt_chars=0`。
- backlog: 超过扫描上限只记录 `interop.pending_backlog` observability，不再生成“另有 N 条待处理消息” prompt；coordinate/task 留给 E26 条件外部输入治理。
- subagent 语义复核: `SubAgentResult.reports` + `spawn_subagent` tool receipt 已是父模型的真实语义通道，因此 inbox notify 只是重复第二通道；退出 prompt 后工具结果能力不丢失。
- 当前实证: direct pending=0；done notify=50；processed history=168（notify=166 / coordinate=2）；历史 `[外部协调·from DSH]` artifact occurrence=252（仅证明 reachability，不当作请求率）。
- 验证: implementation commit `a25670c` detached clean；focused **23/23 PASS**；broader tracked E25 adjacent suite PASS；scheduler **16/16 PASS**；production pyright **0/0**；changed-test ruff PASS；R0-1~R0-4 PASS；frozen hash `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a` 不变；checkout before/after clean。
- channel UX note: `wake=False` scheduler reminder 现在作为 UI/event state；若飞书需要主动提醒，应走 output-side direct notification，不应恢复 LLM prompt 注入。
- Matrix: E25 OPEN→DONE；总计 `DONE=23 / KEEP=1 / PARTIAL=10 / OPEN=0`；behavior canary 仍只 READY，未启动。
- evidence: `docs/injection-governance/eligibility/r812-report.md`、`eligibility/matrix.json`、`tests/unit/test_interop_inject.py`、`tests/unit/test_subagent_report.py`、`tests/web/test_interop_api.py`。
- evidence_required: true

## R8.13 Conditional External Input Authority Closure — ✅ PASS
- E26 `interop_coordinate_or_task`: pending coordinate/task no longer becomes program prompt material; zero Message, zero provider chars, no automatic consume. Body remains in interop pending/UI for explicit handling.
- Root cause: watcher previously guessed the most-recent/default session and fabricated `协调通道有新消息待处理...` as user text. Current historical coordinate census=2, both scheduler `ref=sched-*` with no target session, so recency was not a valid relation proof.
- Watcher: `_on_inbox_notify` records global action observability only; no guessed session event. Legacy `INBOX_WAKEUP` callback records `blocked_no_user_authorization` and never starts `BackgroundRunner`.
- Legacy replay: pre-upgrade `_interop_tail_messages` / interop deferred refs are retired before build so err1210 compatibility state cannot resurrect external prompt authority.
- Central hard gate: commit `d2fc3fe` removes `interop` from `PROMPT_DYNAMIC_PRODUCER_SLOTS`; a future producer cannot regain eligibility merely by using the old slot label.
- Future allowed path: only explicit input-side user accept/insert may upgrade an external item into genuine user-authorized task input. `target_session`/`ref`/recency alone are not authorization.
- Verification: implementation commits `8cd2884` + `d2fc3fe`; final detached clean production pyright 0/0; focused + broader tracked interop/watcher/Web/scheduler/job/subagent/factory/1210/eligibility/model-attribution suites PASS; R0-1~R0-4 PASS; checkout before/after clean. Untracked parallel `test_schedule_wake.py` supplementary 5/5 PASS and not committed in this batch.
- Matrix: E26 PARTIAL→DONE；总计 `DONE=24 / KEEP=1 / PARTIAL=9 / OPEN=0`；behavior canary / R9 未启动。
- evidence: `docs/injection-governance/eligibility/r813-report.md`、`eligibility/matrix.json`、`tests/unit/test_interop_inject.py`、`tests/unit/test_factory.py`、`tests/unit/test_prompt_eligibility_r88.py`。
- evidence_required: true

## R8.14 Task Handoff Authorization Closure — ✅ PASS
- E24 `task_hotcard`: cross-session / unconsumed / recency no longer grants prompt authority. `write_hotcard` remains durable; normal build does not pop/inject/consume it.
- Real counterexample: current `data/handoff/task_hotcard.json` was `consumed=false` while its anchor belonged to an unrelated MLX/model task and its active-goal checkpoint was an older injection-governance R0→R1 state. This proves session inequality is not continuation intent.
- `pop_hotcard` / `reset_hotcard_consumed`: default deny; only an already user-authorized restore/accept path may pass `authorized=True`.
- err1210: legacy HOTCARD entry => `defer_dropped(reason=prompt_eligibility_retired)`; no consumed reset, no replay marker, no re-injection.
- central hard gate: `hotcard` removed from `PROMPT_DYNAMIC_PRODUCER_SLOTS`; semantic reference classification alone cannot grant automatic prompt access.
- retrieval preserved: full card JSON remains at `data/handoff/task_hotcard.json`; `handoff_now` + ArchiveStore/search_archive remains an independent explicit recovery channel.
- reachability census: current event-log payload content has 0 runtime-like `[任务热卡]` frames; three literal occurrences were tool/source-code output. Risk was reachable/currently armed, not asserted as widespread request pollution.
- golden: live morphology now memory+tip only; reviewed digest `59a823f60750e5b96565bf46057f141e33d7e328ae0b67b3e3a250dfa5ac5e64`; writing a hotcard is proven wire-neutral and leaves consumed=false.
- verification: implementation `223472c`; detached clean production pyright 0/0; focused **89/89**; broader **289/289**; R0-1~R0-4 PASS; checkout before/after clean. Pre-batch `test_task_hotcard` had 2 stale R3 pointer-content assertions; replaced by current authorization contract.
- Matrix: E24 PARTIAL→DONE；总计 `DONE=25 / KEEP=1 / PARTIAL=8 / OPEN=0`；behavior canary / R9 未启动。
- evidence: `docs/injection-governance/eligibility/r814-report.md`、`eligibility/matrix.json`、`tests/unit/test_task_hotcard.py`、`tests/unit/test_handoff_archive.py`、`tests/unit/test_err1210_recovery.py`、`tests/unit/test_injection_fingerprint.py`、`tests/unit/test_prompt_eligibility_r88.py`。
- evidence_required: true

## R8.15 Experience Catalog On-Demand Closure — ✅ PASS
- E08 `experience_tip`: generic post-tool experience/skill catalog no longer gets automatic prompt authority.
- Historical census: 122 persisted role=user tips / 34 sessions / ~49.9k chars; 116 legacy prose + 6 R3 pointers; 46/103 identified rows were above turn 100. Current ExperienceStore: 132 docs, 130 active.
- Root cause: front-K/task-switch + tool-name relevance + unseen-ref dedup proves only candidate relevance/volume control, not required-now.
- Producer: `_inject_experience_tips` is compatibility observability only; no store lookup, skill scan, Message append or session mutation; optional action=`experience.catalog/on_demand_only`, `prompt_chars=0`.
- Provider lifecycle: canonical `metadata.injection_kind=experience_tip` is centrally denied even when turn_ref matches current turn; ordinary human discussion without program metadata is preserved.
- Capability preserved: `search_records(kind=experience)` keyword + exact `experience:<id>` hydration stays; typed/failure-specific tool recovery and experience guidance stay unchanged.
- Verification: implementation `d04986b`; detached clean pyright 0/0; focused/preserved **132/132**; broader **288/288**; R0-1~R0-4 PASS; checkout before/after clean.
- Matrix: E08 PARTIAL→DONE；总计 `DONE=26 / KEEP=1 / PARTIAL=7 / OPEN=0`；behavior canary / R9 未启动。
- evidence: `docs/injection-governance/eligibility/r815-report.md`、`eligibility/matrix.json`、`tests/unit/test_tool_experience_inject.py`、`tests/unit/test_prompt_eligibility_r88.py`、`tests/integration/test_experience_integration.py`、`tests/unit/test_experience_guidance.py`。
- evidence_required: true

## R8.16 Task Execution Identity Closure — ✅ PASS
- E23 `task_frontier`: full graph no longer gains prompt authority merely because an active Goal has a non-empty task ledger. Old slot `task_frontier` is removed from the central dynamic producer allowlist.
- New automatic surface: `task_active` only when there is exactly one `in_progress` task; content is byte-stable `goal_id + task_id + status=in_progress + normalized one-line title` and remains CRITICAL_STATUS for budget survival.
- Zero/ambiguous rule: all-done、ready-only、blocked-only、unreachable-only、0 in-progress and >1 in-progress all produce `prompt_chars=0`; the program does not auto-select a ready task or guess among concurrent tasks.
- Retrieval preserved: `task_frontier()` still returns ready/in_progress/blocked/unreachable/premise_stale and `full=true` waiting/done details；`get_goal` still returns compact task counts；CORE `get_tool_schema` can discover the full tool.
- Current data evidence: 2 task ledgers / 11 tasks / 11 done / 0 open；one Goal is still active with 2 completed tasks, so the former path would emit ~120 chars/turn despite no executable node. Historical ledger replay max concurrent in_progress=1 for both real graphs.
- Wire evidence: frozen captured provider fixtures contain 3 genuine role=user auto frontier messages around 322 chars. Representative synthetic graph full render 286 chars → task_active 117 chars (**-59.1%**); current all-done graph 120 → 0.
- Budget side effect: after prompt shrink the production-shape budget fixture used only 643 chars, below its old 900-char red-light threshold; test threshold moved to supported minimum 512 so over-budget receipt semantics remain covered without requiring prompt bloat.
- Verification: implementation `06dfd6b`; detached clean pyright **0/0**；focused **56/56**；broader **263/263**；R0-1~R0-4 PASS；frozen hash `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a` unchanged；checkout before/after clean。
- Matrix: E23 PARTIAL→DONE；总计 `DONE=27 / KEEP=1 / PARTIAL=6 / OPEN=0`；behavior canary / R9 未启动。
- evidence: `docs/injection-governance/eligibility/r816-report.md`、`eligibility/matrix.json`、`tests/unit/test_task_active_prompt_r816.py`、`tests/unit/test_prompt_eligibility_r88.py`、`tests/unit/test_injection_budget.py`。
- evidence_required: true
