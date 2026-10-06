# PLAN-20261006 FR-1 Learning Method Semantic 生产激活 — 授权包

Date: 2026-10-06
Status: **AUTHORIZED — A1 已授权（2026-10-06 19:48:53 会话明示），A2/A3 按包默认生效；执行记录见 §10，T+0 证据见 §11。**
上游: DESIGN-20261006 §3 FR-1；PLAN-20260926（qualification 证据 + 8 步 Production boundary runbook）
裁决采纳: 2026-10-06 用户转达外部裁决——FR-1 激活准备为主线、停在 mutation 之前、补轻量 currentness gate、不直接执行生产激活；Q1 并行只读（已闭环：ASSESS-20261006-q1）；Q2 后置到 FR-4 开工前。

## 0. 隔离声明（先于一切）

- FR-1 的依据是 **PLAN-20260926 Learning Method semantic isolated qualification**（canonical tool 7/7 rank#1；A/B：OFF 0/3 vs ON 3/3 阻止冗余铸造；159/159 回归 PASS）。
- 同仓库另一条研究线 **Method Subject-Binding v3 已于 2026-10-06 冻结为 EFFICACY_NOT_QUALIFIED、line retired**（commit a33f6312；RESULT-20261006 / POSTMORTEM-20261006；92/92 attempt0）。
- 两者是**不同裁决面，证据互不借贷**：v3 的 no-promotion 不构成对 FR-1 的反对证据；FR-1 的 PASS 也不得用于给 subject-binding v4 复活背书。任一边引用另一边证据即为越界。

## 1. 授权对象：单变量、单服务、零代码变更

| 面 | 内容 |
|---|---|
| 唯一变量 | Learning 服务级 override：SEMANTIC_METHOD_ENABLED 0→1（per-service，经 managed authority 持久化） |
| 保持不变 | Archive/Docs/Experience semantic 均 0；canonical .env 全局默认值（.env:269 SEMANTIC_METHOD_ENABLED=0）不在本次范围 |
| 服务面 | 仅 Learning（restart_target=learning）；Web/Feishu 零接触（PID 对照为验收项） |
| 代码面 | 零代码变更：qualification commit bfd82cba7 已在主干，运行时 a519f41b 已含该路径 |
| 回滚面 | 仅清除该 Learning override（见 §6） |

## 2. 当前基线快照（2026-10-06 17:0x 本会话实测）

- workspace HEAD `a33f6312`（17:05:36）；运行时 HEAD `a519f41b`、generation 180、started 16:38:13+08:00、model glm/glm-5.3、config_hash 6415cdd8…、restart_required=false。
- runtime→workspace 漂移 = 2 commits（7808bd477 v4 post-mortem、a33f6312 v3 冻结），**仅 docs/evals，无 src**。
- .env:267-271：SEMANTIC_MEMORY=1 / ARCHIVE=0 / METHOD=0 / DOCS=0 / EXPERIENCE=0；运行时 semantic_scopes 与之一致。
- 方法池（活跃增长中）：16:3x knowledge_health total 626（c593/h28/q1/a2/r2）→ 17:1x 锚定计数 639（c606/h28/q1/a2/r2），增量全 candidate。
- **语义权威集（active∪qualified）当前 = 3 张**：fresh-read-authoritative-record-before-finality-claim（active）、resume-continuation-via-named-provenance-and-git-delta（active）、self-execute-review-contract-on-degenerate-tool-output（qualified）。
- qualification 基线 commit `e04172f2`（gen 115，09-26）；该基线以来 FR-1 六路径净变化 **+766/−65**（factory +291 / config +257 / reflection +179 / resolver +63 / learning_plane +36 / manifest +5）——漂移实质存在，§3 G1 为必过门。

## 3. 执行前 currentness gate（G1–G5 全 PASS 才进入 §4；任一 FAIL → 停止并回到 qualification 重跑，不继续）

- **G1 代码路径审查**：`git diff e04172f2..<执行时HEAD> -- src/llm_loop/factory.py src/llm_loop/config.py src/llm_loop/runtime/manifest.py src/llm_loop/runtime/resolver.py src/llm_loop/methods/learning_plane.py src/llm_loop/methods/reflection.py`，逐 hunk 核对四项契约仍在：
  ① method_discovery 回调仅在 Learning semantic_method_enabled=true 时注入（factory.py:2019-2078 现位）；
  ② 权威集过滤 active∪qualified（reflection.py:312 `_DEDUP_STATUSES`、:386 契约文字）；
  ③ discovery fail-open + 机械诊断（learning_plane.py:460-467 现位）；
  ④ API embedding 故障时 primary_to_hash fallback 可见化。
  任一契约级改动 → FAIL。
- **G2 canary 集重derive**：canonical smoke 目标集按**执行时** active∪qualified 重新生成（当前 3 张；09-26 的 7 家族 artifact 仅作历史参照——其中 4 张已不在权威集）。集合 <3 时 warning，人工裁决。
- **G3 测试门**：在执行 HEAD 重跑 focused 65 + broad 159 等价集 + Ruff + compileall（tests/unit/test_method_learning.py 与 6 件 20260926 eval artifact 均在位）。
- **G4 runbook-schema 对齐**：执行时核对 service_control 当前 schema（update/publish 参数语义、idle gate、expected_generation CAS），与 §4 映射不一致处以当时 schema 为准并回写本文。
- **G5 池/侧车健康**：embedding 侧车错误=0、队列 idle；candidate 池继续增长不阻塞（不进权威集）。

## 4. 执行序列（8 步 runbook → 动作面；每步落证据）

| # | runbook 步骤 | 动作面 | 证据 |
|---|---|---|---|
| 1 | 干净候选经 managed authority 发布 | 工作树 clean（含本包与 Q1 报告提交）→ service_control publish | 发布回执（新 generation、绑定 HEAD、产物 hash） |
| 2 | 仅 Learning Method override 持久化 | resolver per-service override；Archive/Docs/Experience 保持 0；canonical .env 默认不动 | override 工件 + provenance |
| 3 | dry-run | resolver / manifest / config-hash / knowledge binding | dry-run 输出存档 |
| 4 | Learning idle gate → 单服务重启 | service_control restart（restart_target=learning，expected_generation=当前+1） | idle gate 回执 + 重启终态 |
| 5 | manifest 验证 | Memory=1 / Method=1 / Archive=Docs=Experience=0 + per-service provenance 正确 | manifest 快照 |
| 6 | smoke 重跑 | G2 集合 canonical tool/model + journal e2e + Memory 兼容 | smoke JSON（对标 20260926 artifact 结构） |
| 7 | 无扰验证 | Web/Feishu PID/健康对照、embedding 错误=0、队列回归 idle | PID 对照表 + 计数 |
| 8 | 回滚（仅 stop condition 触发） | 见 §6 | 回滚后 manifest + smoke 基线复跑记录 |

## 5. Canary 成功标准与 stop conditions

**成功（全部满足才算激活成立）**
- §4-5 manifest 精确匹配；§4-6 G2 集合 rank#1 = N/N、semantic-effective N/N、0 fallback、0 missing vector。
- journal e2e 一次到 terminal，Method 计数不增；§4-7 Web/Feishu PID 不变、embedding 错误 0、队列回归 idle。

**Warning（人工裁决继续/停，不停机）**
- semantic_fallback_reason=primary_to_hash 出现但 rank 保持 #1（fallback 可见化属设计内行为）。
- 单次 embedding 超时自愈、队列瞬时忙后回归 idle。

**Critical（立即 §6 回滚）**
- G2 集合任一目标 rank>3 或 missing vector / fallback 常驻。
- Learning 启动阻塞、journal 反复重试不 terminal。
- Web/Feishu 任何 PID/健康变化（单服务边界被突破）。
- embedding 错误单调增长不收敛。
- method_discovery 出现 fail-open 之外的异常路径或 Reflection 输出退化。

## 6. 回滚面（精确、最小）

- 对象：仅 Learning Method override → 恢复 Method=0。不含代码回退、不含其他服务、不含 canonical .env 全局值。
- 序列：清 override → dry-run 复核 → restart learning → manifest 复核 Method=0 → Memory 兼容 smoke 复跑 → 全程留痕。
- **演练口径（owner 裁决点 R-1）**：DESIGN 验收原文"回滚演练一次成功"。选项 a) 激活成功后做一次完整 回滚→重激活 真演练（多一次重启窗口）；选项 b) 仅做回滚能力验证（dry-run 清除路径 + 纸面预演），真回滚保留给 stop condition 实际触发时执行并留痕。**本包默认 b，请 owner 明示。**

## 7. 观测窗口与最终证据（对接 FR-3）

- T+0：激活证据包落盘（manifest、smoke JSON、PID 对照、发布/重启回执链）。
- T+24h / T+7d / T+28d：embedding 错误与队列、semantic_fallback_reason 分布、method_discovery 命中/采纳（顶层 usage.jsonl 口径）、Web/Feishu 健康、权威集与池快照（带时间戳）。
- 窗口内 semantic_experience/docs 保持 0（Q4 复议前置）；任何 Critical 触发的回滚全程留痕。

## 8. 明确不做（与 DESIGN §2 非目标一致）

不扩 semantic_experience/docs；不批量 qualification；不动 384 张 dead-but-harmless 与 27 张批量 hold 卡；不借 subject-binding v3 任何证据；不新增白名单域；本文档不构成授权。

## 9. Owner authorization checkpoint

- [x] A1 授权按本包执行 FR-1 生产激活（含执行窗口选择）—— 2026-10-06 19:48:53 会话明示："授权按包执行 FR-1 生产激活（含窗口选择）"。
- [x] A2 回滚演练口径 R-1 —— 按包默认 **b**（回滚能力验证：dry-run 清除路径 + 纸面预演；真回滚保留给 stop condition 实际触发时执行并留痕）。未显式改判，随 A1 按包生效。
- [x] A3 观测报告节奏 —— 按包默认 **T+24h / 7d / 28d**。同上。
- 授权记录：2026-10-06 19:48:53 / 本会话用户消息 / 全包范围（单变量 SEMANTIC_METHOD_ENABLED Learning 0→1 + §4 runbook + §6 默认 b + §7 默认节奏）/ owner=会话用户。

## 10. 执行记录（2026-10-06 晚间窗口）

- **窗口选择**：2026-10-06 ~20:00（晚间低流量；learning journal pending=0，embedding 侧车无请求错误，Web/Feishu 空闲）。
- **G1 PASS**：`e04172f2..执行HEAD` 六路径 diff（1222 行）全 hunk 审读。四项契约全部在位：① factory.py `if settings.semantic_method_enabled` 注入门在位；② `_DEDUP_STATUSES`=active∪qualified 过滤与 payload 契约文字在位；③ discovery fail-open + `discovery_error`/诊断字段在位；④ `primary_to_hash`（retriever.py:1148）自 e04172f2 **零漂移**（该文件不在六路径且无 diff）。其余漂移均为无关特性：browser attestation/profile 重构、chatgpt/deepseek web provider 配置面、knowledge path bootstrap、learning model 治理入 schema。
- **G2 PASS**：执行时权威集（active∪qualified）= 3 张：`fresh-read-authoritative-record-before-finality-claim-35fe91da2cd4`（active）、`resume-continuation-via-named-provenance-and-git-delta-948a229d7f50`（active）、`self-execute-review-contract-on-degenerate-tool-output-c1088a737f27`（qualified）。canary 按此 3 张执行（09-26 的 7 家族口径仅作历史参照）。
- **G3 PASS（含一次机械处置）**：聚焦+邻接 117/117（13 文件，为 65 口径超集）；broad 邻接（foreground/provider-settlement/web-stream 15 文件）**206/206**（159 口径超集）；Ruff 六路径全绿；compileall PASS。Ruff 首跑 1 处**存量** I001（factory.py import 乱序，browser 漂移引入、与四契约无关、运行时代码同样存在）→ `ruff --fix` 纯 import 重排（diff 仅 3 行移动，行为零变化）单独 commit 后复跑全绿。
- **G4 PASS（无实质偏差）**：当前 schema 下 publish 与 restart 为独立动作、restart 异步两阶段、`expected_generation` 缺省取当前期望代（与 §4-4 "当前+1" 等效）、publish 要求 tracked 树干净。§4 映射无需改写。
- **G5 PASS**：journal 1183 job 无 pending（saved 762 / none 141 / failed 253 / cancelled 27）；embedding stderr 无请求错误（仅 1 处 resource_tracker UserWarning）；knowledge healthy；lfrt runtime-observation ok。基线上文（非 FR-1 面）：18:02 存量 1 条 `reflection_call_failed` 终态 job，激活前发生，列入 T+24h 观察对照。
- **执行链与证据**：见 §11。执行时间线：commit `337e2855f`（机械 lint）+ `3e502592b`（授权包/知识工件）→ publish **gen 181**（deploy-12fd22aa194c46fcb396f1390b9d4bbe, HEAD 3e502592b）→ runtime.toml `[semantic.learning] method=true` → dry-run PASS → restart learning（svc-a713b14ce45245c2a2fc9e18c919f3ce, 2.4s, verify=confirmed_ok）→ manifest/无扰动核验 → canary PASS。

## 11. T+0 证据包（2026-10-06 20:1x）

- **发布/重启回执**：desired gen **180→181**（webui sha 52970dd2…，git_head 3e502592bba38e88a309d8fa958a1c6a09712594）；restart action `svc-a713b14ce45245c2a2fc9e18c919f3ce` status=succeeded，learning 新 PID **68464** @19:59:29，head=3e502592b（仅 learning 重启；web/feishu 保持 gen 180 进程，属预期——代差仅为 docs+import 重排+知识工件）。
- **Override 工件**：runtime.toml 追加段（含授权注释）；dry-run JSON `evals/retrieval_ab/fr1-activation-dryrun-20261006.json`（sha256 bbbb5989…）：learning `SEMANTIC_METHOD_ENABLED=1 ← runtime_toml_service:learning`，其余 4 个 semantic 键与 web/feishu 全部键不变（dotenv）。单变量判定 PASS。
- **R-1b 回滚能力验证 PASS**：剥离 `[semantic.learning]` 段投影回 `0 ← dotenv`（`/tmp/fr1/runtime.toml.rollback` 等价验证）；回滚动作 = 删 5 行配置，零代码/.env 牵涉。
- **Manifest 核验**：learning semantic_scopes = {memory:1, method:**1**, archive/docs/experience:0}，scope_sources.method=`runtime_toml_service:learning`，其余 dotenv —— 与 §1 期望完全一致。
- **PID 对照**：web **40200**（16:38:13 不变）、feishu **40406**（16:38:29 不变）、learning 40913→**68464**。无扰动 ✅。
- **Canary smoke PASS**（`evals/retrieval_ab/fr1-activation-t0-canary-20261006.json`）：G2 3/3 **rank#1 + semantic_effective + 零 fallback**（bge/api 8765 主引擎）。生产视图实测 8 员 = 3 权威卡 + 5 个 active 种子方法（method-ab-experiment / method-repo-api-discovery / method-root-cause / method-self-distill / method-semantic-operation）——与 factory 同构（store 含 seed_dir），非口径偏差；knowledge_health 的 630 池口径只计 data/methods。种子方法进 Learning dedup 权威视图与 qualification 时点一致（当时 7 active 家族亦含种子）。
- **Memory 兼容**：进程级证据 = web/feishu 进程未动 + memory 旗标 dotenv=1 未变 + 侧车错误增量 0。独立探针（rank_cached_candidates）= **调用契约错配（candidate_cache_cold → 按契约 fail-open，只读+调度后台修复）**，不构成生产回归证据也不构成反证；如实记录。
- **Sidecar/队列终态**：embedding stderr 错误计数全程 =1（仅存量 HF UserWarning，增量 0）；learning journal pending=[] 维持 idle。
- **Stop conditions**：零触发（无 candidate 激增、无队列阻塞、无侧车错误、无 web/feishu 扰动、无 config_hash 漂移）。
- **基线观察项（非 FR-1）**：18:02 存量 `reflection_call_failed` 终态 job；web/feishu 滞后 gen 181 一代（下次自然重启收敛，无需动作）。
- **T+0 状态结论**：**FR-1 生产激活完成，无 stop condition**。观测进入 A3 默认节奏：T+24h（2026-10-07 晚）/ T+7d / T+28d，判据按 §5。
