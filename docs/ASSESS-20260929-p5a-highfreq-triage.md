# ASSESS-20260929 P5-A 高频 25 张 candidate 分诊（只评估不处置）

依据: EVO-20260929-5283ab1b P5-A（census 建议 A，用户授权执行）。25 张 = 出现在真实 query top-5 ≥4 次的 candidate（/tmp/census/appear.json，重放口径同 census §2）。
判定原则: 使用证据严格认 usage.jsonl（25 张全部 u=0）；本会话行为不追溯计 use（防 goodhart）。处置建议仅供独立裁决，本文档未执行任何生命周期变更。

## 分诊表

| # | 卡（次数/qual） | 分类 | 依据 | 处置建议 |
|---|---|---|---|---|
| 1 | trust-durable-completion-evidence-on-resume (8/0) | retrieval-noise（带独立增量） | 与 active resume-continuation 重叠，但"落盘哨兵（EXIT 行/mtime 稳定）判定后台验证已闭合"是独立子场景；本轮全量测试后台哨兵读取即该场景 | 建议独立 qualification（增量面真实） |
| 2 | verify-presupposed-failure-via-live-metrics-and-record-scope (7/0) | 独立增量候选 | "对预设失败先查活指标+记录作用域再扩大重验"是独立验证纪律，不与 active/qualified 卡重叠 | 建议 qualification |
| 3 | record-use-v3 (7/1) | stale-currentness-risk | 卡内 record_use 纪律描述已被 EVO-20260929-5283ab1b v2.2 生命周期（判定即落账+配对+独立处置）实质取代 | 建议积累独立证据后 invalidate 或重写对齐 v2.2 |
| 4 | verify-explicit-handles-before-broad-status-discovery (6/1) | 独立增量候选 | "先用精确 handle 水合再做宽发现"独立纪律；本会话 grounding/handle 机制持续适用 | 建议 qualification |
| 5 | structural-record-attribution-before-paraphrase-grep (6/0) | retrieval-noise | fresh-read-authoritative-record（active）覆盖其主语义（先读权威记录再断言） | 暂不动；若处置需独立证据 |
| 6 | resume-partial-reads-at-continuation-pointer (5/0) | 独立增量候选 | "从上次分页指针续读"与 read_evidence range/next_start 机制直接对应，场景独立 | 建议 qualification（可绑 freshness_refs=read_evidence 所在面） |
| 7 | isolate-via-linked-worktree-when-dirty-state-disjoint (5/0) | 独立增量候选 | 脏树/旁路副本隔离为独立工程纪律，worktree 机制在库 | 建议 qualification |
| 8 | poc-a-b (5/1) | 独立增量候选 | A/B 对照验证法与 EVO P6 验收序直接对应 | 建议 qualification |
| 9 | read-record-evidence-citations-before-filename-search (5/1) | retrieval-noise | evidence:// 引用优先于文件名搜索——fresh-read 卡+规则层已覆盖主语义 | 暂不动 |
| 10 | paste-integrity-before-failure-diagnosis (4/1) | 独立增量候选 | 粘贴件完整性校验独立场景 | 建议 qualification |
| 11 | verify-endpoint-from-live-process-after-restart (4/0) | 独立增量候选 | 重启后以活进程核验端点，独立验证面 | 建议 qualification |
| 12 | route-semantics-verification-to-authoritative-tree (4/0) | retrieval-noise | "语义问题路由到权威树"为 fresh-read/证据纪律变体 | 暂不动 |
| 13 | exact-id-lookup-in-system-of-record-before-semantic-search (4/0) | retrieval-noise | 精确 ID 先于语义检索——9 号同族变体 | 暂不动 |
| 14 | recover-prior-session-state-from-artifacts-named-in-receipts (4/0) | retrieval-noise | resume 族子变体（从回执命名工件恢复） | 暂不动 |
| 15 | resume-interrupted-run-verify-traced-artifacts-before-re-discovery (4/0) | retrieval-noise | resume 族子变体 | 暂不动 |
| 16 | method-candidate-ab-validity-trigger-confound (4/1) | 独立增量候选 | A/B 效度判别（触发混淆控制）为 P6 评估方法学的组成部分 | 建议 qualification |
| 17 | status-question-provenance-first (4/1) | retrieval-noise | 状态问题先问出处——规则层"以当前工具回执为准"已覆盖 | 暂不动 |
| 18 | time-anchored-regression-window-first (4/1) | 独立增量候选 | 时间锚定回归窗口为独立诊断纪律 | 建议 qualification |
| 19 | resume-from-freshest-verified-evidence-edge (4/0) | duplicate-family | 与 active resume-continuation（最新已验证证据边续跑）同族 | 建议独立证据后 disposition |
| 20 | repo-owned-qualification-harness-first (4/0) | 独立增量候选 | 资格化 harness 归仓——与 P5/P6 实践直接对应 | 建议 qualification |
| 21 | verify-ref-attachment-before-push-from-temp-worktree (4/0) | 独立增量候选 | 推送前核验引用附着，独立操作面 | 建议 qualification |
| 22 | epoch-scoped-evidence-before-liveness-claim (4/0) | 独立增量候选 | epoch 作用域证据先于存活断言，独立验证面 | 建议 qualification |
| 23 | vague-referent-resolve-via-git-provenance (4/0) | retrieval-noise | 含糊指称经 git 溯源——23 号与 5/9 号族相近但 git 面独立 | 暂不动（边缘） |
| 24 | resume-active-goal-from-checkpoint-git-delta-skip-reveri… (4/0) | duplicate-family | checkpoint+git delta+跳过重验证与 active resume-continuation 高度同族 | 建议独立证据后 disposition |
| 25 | adversarial-cross-review-before-high-stakes-output (4/1) | 独立增量候选 | 高风险产出前对抗性交叉评审——本 EVO v2.2 的外部评审实践即为该场景 | 建议 qualification |

## 汇总

- 独立增量候选（建议 qualification）: 12 张（#1,2,4,6,7,8,10,11,16,18,20,21,22,25 中取 12——#1 标注为带增量的 retrieval-noise 计入此处建议）
- retrieval-noise（暂不动，处置需独立证据）: 9 张（#5,9,12,13,14,15,17,23 及 #1 若不计增量）
- duplicate-family（建议独立证据后 disposition）: 2 张（#19,24）
- stale-currentness-risk: 1 张（#3 record-use-v3，被 v2.2 生命周期取代）
- dead-but-harmless: 0；has-real-use-awaiting-qualification: 0（严格口径 u=0）

## 建议执行顺序（供独立裁决采纳）

1. 先处置 #3（stale，重写或 invalidate 需独立证据）
2. #19/#24 同族二选一保留（另一张 invalidate，需 ≥2 episode rejected 或 qualification fail 的独立依据）
3. 12 张增量候选逐张 qualification（每张须独立于蒸馏会话执行，只认 task_benefit 实证——建议在后续真实任务命中时逐张补，不批量刷）
4. retrieval-noise 9 张不动（与 active 卡共存成本低：active +35 权重已保障召回优先级）
