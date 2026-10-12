# ASSESS-20260929 Method Pool Census + Retrieval Pollution Eval（P5，只读）

依据: EVO-20260929-5283ab1b P5（accepted）。本报告**只有机械事实与处置建议**，未执行任何生命周期变更。
方法: MethodStore 只读扫描 + 71 条**真实历史** search_records(kind=method) query 重放（自 data/event_logs 提取），
limit=5（与生产默认一致），反事实组排除 candidate 复算排序。
脚本与数据: /tmp/census/{data.json,appear.json}（一次性，未入库）。

## 1. 池子总体（n=555）

| 状态 | 数量 |
|---|---|
| candidate | 550 |
| active | 2 |
| hold | 1 |
| retired | 2 |
| qualified | 0 |

- 有 qualification 记录: 66；有 usage 记录: 2；有 applied/adapted 使用: 1
- 声明 freshness_refs: 1（unbaselined——qualification 未对其实际基线化）
- 年龄分桶: ≤7 天 208，8–30 天 344，>30 天 0；中位 9 天
- 正文缺六节 Card Contract 结构: 35（candidate 32 / retired 2 / hold 1）
- 同名/同族重复（归一化 name core）: 0 —— name 去重有效

## 2. 重放结果（71 条真实 query）

- top-5 含 ≥1 candidate 的 query: **70/71**
- candidate 把更高生命周期权重的卡挤出 top-5 的 query: **38/71**
- 被挤出的高价值卡仅 3 张（反复出现）: resume-continuation-via-named-provenance(active)、fresh-read-authoritative-record(active)、lfl-mirror-qualified-worktree(hold)
- 出现在 ≥1 个 top-5 的 candidate: 166/550
- 其中零 qualification 且零 use: 125
- 出现 ≥4 次的高频 candidate: 25

高频 candidate 前十（出现次数）: trust-durable-completion-evidence-on-resume(8)、verify-presupposed-failure-via-live-metrics-and-record-scope(7)、record_use证据披露与评估纪律 v3(7)、verify-explicit-handles-before-broad-status-discovery(6)、structural-record-attribution-before-paraphrase-grep(6)、resume-partial-reads-at-continuation-pointer(5)、isolate-via-linked-worktree…(5)、冻结件PoC验证法(5)、read-record-evidence-citations-before-filename-search(5)、paste-integrity-before-failure-diagnosis(4)。

## 3. 分类（v2.2 分类法，机械判定）

| 类别 | 数量 | 成员特征 |
|---|---|---|
| has-real-use-awaiting-qualification | 1 | self-execute-review-contract-on-degenerate-tool-output（applied=1, qual=0） |
| stale-currentness-risk | 2 | 两张 active 卡 freshness=unbaselined（无 freshness_refs；P3 上线后可在 qualification 时基线化） |
| retrieval-noise | 166→重点 25 | 出现在真实 query top-5 的 candidate；高频 25 张为主要干扰源 |
| duplicate-family | 0 | —— |
| dead-but-harmless | 384 | 从未出现在任何重放 top-5、零 use、零 qualification 的 candidate（550−166） |

## 4. 结论（机械事实层面）

1. "550 张 candidate 都在污染检索"不成立：真正进入 top-5 的是 166 张，高频干扰集中在 25 张。
2. 但污染真实存在且定向：38/71 真实 query 中，同一小撮 candidate 系统性挤掉仅有的 2 active + 1 hold 高价值卡。
3. 生成/收敛失衡确凿：中位年龄 9 天、555 张里 66 有 qualification、2 有 use、0 qualified——**qualification 与 use 回流几乎没发生**，这是主要病灶，不是卡片数量本身。
4. 35 张结构性缺陷卡（缺节）已被 P2 契约挡在未来写入之外；存量不影响新写入面。

## 5. 处置建议（提案，不执行——处置权在独立裁决）

- **P5-A（最高价值）**: 高频 25 张 candidate 逐张独立评估——真实相关者走 record_qualification + freshness_refs 基线化；确认过时者积累独立证据后经 refine(invalidate) 处置（新前置会强制要求独立依据）。
- **P5-B**: 两张 active 卡补 freshness_refs 并重新 qualification，消除 unbaselined。
- **P5-C**: 1 张 has-real-use 卡补 qualification（已有 applied 使用证据，最接近可 qualified）。
- **P5-D**: 384 张 dead-but-harmless 不动——不造成检索干扰，批量 invalidate 无收益且有系统性误杀风险。
- 顺序建议: 先 C/B（补正向闭环），后 A（高频分诊），D 保持不动。

## 6. 执行记录（2026-09-29 23:4x，用户授权"按建议执行"）

- **P5-C 已执行**: self-execute-review-contract-on-degenerate-tool-output 经独立评估 record_qualification（verdict/mechanism/task_benefit=pass，promotion=pass，评估任务独立于源 episode 5adf278f）+ refine(qualify) → **qualified**（池内首张）。
- **P5-B 已执行**: 两张 active 卡补 freshness_refs（fresh-read→service_control.py；resume-continuation→search.py，受控 frontmatter 编辑，git 可回滚）+ 重 qualification 落 SHA 基线 → freshness state=**current**，unbaselined 清零。
- **P5-A 进行中**: 25 张高频 candidate 清单重建（/tmp/census 原始数据仍可用），子代理逐张分诊中，结论落 docs/ASSESS-20260929-p5a-highfreq-triage.md；处置仍待独立裁决。
- **P5-D 维持不动**。
- 附带发现: P4 的 use_decisions/with_usage 首版扫方法目录内 */usage.jsonl 而实际记录在顶层 usage.jsonl（指标恒空的扫描 bug），已修正为顶层单文件按 method_ref 计数——修正后实测 applied=2、with_usage=2。
