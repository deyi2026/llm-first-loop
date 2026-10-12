# ASSESS-20261006 Q1 增补 census：hold 1→28 成因核验（只读）

Date: 2026-10-06 17:1x
性质: 只读增补 census（承接 DESIGN-20261006 §7 Q1 / R5）。零生命周期变更、零卡片写入。
方法: 锚定计数（`^status:` per-card frontmatter）+ mtime + git 考古（log --follow / git show <rev>:<path>）。

## 1. 结论

hold 1→28 的成因是 **2026-09-30 15:30:38 一次批量状态迁移**：27 张 candidate→hold，updated_at 全部落在同一亚秒窗口（15:30:38.539–.544，毫秒级递增）。对象是 2026-09-20 由 `472c1163c`（"补收 data/methods 270 张学习方法卡"）入库的旧运行时方法卡（created_at 2026-09-09~09-12），落盘提交为 `f1746f41a`（"chore(data): sync runtime method/experience cards (27 updated, 24 new)"，2026-09-30 15:50:10）。

四分类判定：
- 状态迁移 ✓（candidate→hold 单批，git show f1746f41a^ 抽验 3 张均为 candidate）
- 导入/新增卡 ✗（卡龄 3 周以上，非新铸造）
- 计数口径变化 ✗（两轮均按 status 字段锚定计数；census 09-29 hold=1 与批量 09-30 时序自洽）
- 异常积累 ✗（09-30 后零新增 hold，28 张至今稳定）

## 2. 证据链

1. 28 张 hold 的 updated_at：27 张 = 2026-09-30T15:30:38.539~.544+08:00（单事务窗口）；1 张（lfl-mirror-qualified-worktree）updated 2026-09-18，即 census 期唯一 hold，其后未动。
2. 27 张 created_at 分布：09-09（22）/ 09-10（2）/ 09-11（2）/ 09-12（1）。
3. 溯源口径：24 张 source_episode_refs 为 `session:` 前缀（本仓现行铸造口径为 `episode:`），集中于 d3e8d89f / 2274a444 / 4d6c551c 三个 session；另 3 张为 episode: 溯源（candidate-a80acb208b99、gh-device-push-v2、poc-a-b）。
4. 入库链：`472c1163c`（09-20 01:29，补收 270 张，.gitignore !data/methods/ 保全豁免落地）→ `f1746f41a`（09-30 15:50，27 updated / 24 new 同步）。
5. 状态分布（2026-10-06 17:1x 锚定计数）：candidate 606 / hold 28 / qualified 1 / active 2 / retired 2。

## 3. 决策出处（未核验项，如实声明）

- f1746f41a commit body 无 hold 理由；data/methods 顶层 usage.jsonl 与各卡 qualification.jsonl 均无 hold 转移记录；docs/ 无对应决策文档。
- 判定：**机械成因已闭环（何时、哪些卡、从什么状态迁移到 hold）；决策 rationale 未在仓内留痕**。合理推测（未证，不作为事实引用）：补收的旧运行时卡被一次性隔离。
- 如需补全：查 data/event_logs 2026-09-30 15:30 窗口或人工问询。本轮未做，不影响分类结论。

## 4. 附带口径勘误（计数纪律）

1. `ls data/methods | wc -l` 混入非目录条目（本轮 634 vs 真实卡目录 630）；计数须 `-d */` 或锚定 frontmatter。
2. 卡名含 "status" 字样时非锚定 grep 先命中 method_id 行（本轮 7 张）——knowledge_health 与裸 grep 的 candidate 计数差由此而来。
3. 池子正被活跃会话实时增写：knowledge_health（16:3x）total 626 → 本轮（17:1x）锚定 639，增量全部 candidate。**任何池快照必须带时间戳**。

## 5. 对 FR-1 / DESIGN 的影响与处置建议（不执行）

- 零影响：hold 不进语义权威集（src/llm_loop/methods/reflection.py:312 `_DEDUP_STATUSES = {"active","qualified"}`、:386 契约）；27 张批量 hold 卡与 384 张 dead-but-harmless 同类，不污染 canary、不阻塞激活。
- 处置建议：维持 hold；若未来扩展 P5-A 分诊再一并评估，不单独立项。
- DESIGN-20261006 §7 Q1 可关闭；R5 降级为"已解释"。
