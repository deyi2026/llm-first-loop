# REPORT-20261111 | 并行会话开发模式实施与检验（LFL Peer M1 第一批 P0）

- Goal: GOAL-20261111-3cb818eb | 基线 main=fcfb40270e1dd50cc423934153baf77fb294ddd3 | 终态 main=7a496abe3cc3cb4cdb0a101a1dbba6ee8d6ca693
- 时段: 2026-11-11 16:56–18:26（约 90 分钟，含 3 路并行开发 + 6 轮全量门禁 + 7 次独立审查 PASS + 3 次串行合并）
- 设计依据: docs/design/LFL_Peer_Requirements_Implementation_Design_2026-11-11.md（v1.1，§6.1/§6.3/§6.5，A04–A09）

## 1. 模式

主会话为调度器：3 条正交 lane（worktree+分支）并行开发——Lane-A 原子写入（主会话亲自 TDD）、Lane-B nonce 持久化（子代理）、Lane-C 快照确认（子代理）；验证面并行（2 路全量门禁 + 审查子代理）；合并面串行（队列+全局槽）。三 lane paths 两两不相交是零冲突 rebase 的前提。

## 2. 交付

| Lane | 分支/提交 | 内容 | 测试 | 合并 |
|---|---|---|---|---|
| A atomic | 149c6a422+5c73df7da（replay 自 35242ad3+a2897fc66） | link(2) 原子发布（EEXIST 判冲突/显式不支持拒绝/nlink≥2 提交强证据/父目录 fsync）+ u5_child 签名适配 | 4 红转绿，套件 246（基线 242+4） | ff→main |
| B nonce | 6a638a5ff→af18c1a67→7a496abe3 | nonce 节点/代际/时间窗三级分桶持久化（窗口内结构性永不淘汰，约 337µs/请求 append+fsync）+换钥双代并验+durability registry 登记 | 32 passed（6 红转绿）+守卫 | ff→main |
| C snapshot | 8e78aa58e | TargetSnapshot（lstat+sha256+mode）入票、consume 前复核不烧票、并发双消费恰一胜 | 12 红转绿，40 passed | ff→main |

累计 main 净增 +971/−28。全部通过：RULE-AI-28 审查闸（canonical ci_gate 命令）→ RULE-AI-34 merge-review（独立只读子代理 6 项清单+语义抽查+落盘回执）→ verify 凭证（绑定真实 PASS 回执）→ lane_queue_submit 四项 preflight → confirm/ff/done → lane 自动收口 merged。

## 3. 并行机制检验记录（全部实测，无推测）

| # | 观察点 | 结果 |
|---|---|---|
| 1 | lane_open 占用门 | 通过：peer 相关在途 lane 0 冲突 |
| 2 | lane_update CAS | 通过：expected=2 误用被拒，按回执 current=1 重试成功（RULE-AI-33 语义正确） |
| 3 | 合并队列版本 CAS | 通过：confirm expected=1 被拒 current=3；done expected=5 被拒 current=4——两次按回执重试成功 |
| 4 | 40 位 SHA 口径 | 通过：全程 rev-parse 全长；设计基线与实测零漂移 |
| 5 | 并行执行体可用性 | 通过且推翻旧经验：spawn_subagent 现走远程 glm-5.3（不占本地 prompt_concurrency=1 队列），3 路并行（2 开发子代理 32/31 轮 + 主会话）全部成功；旧结论"并发=1 并行子代理不可用"的前提（子代理挤本地队列）已消失 |
| 6 | 全量门禁兜跨面回归 | 通过：抓到 2 个 lane 内定向测试抓不到的缺陷——u5_child e2e monkeypatch 签名依赖（Lane-A）；durability registry 未登记（Lane-B）。M0 冻结的 tests/peer/ 基线不含 e2e/守卫面 |
| 7 | 审查资格失效-重审循环 | 通过（闸 fail-closed 正确）：pyright 修复、registry 登记、rebase 各触发一次重审，共 7 次 PASS |
| 8 | base 卫生竞态 | 实测 2 次风险窗口：merge-review 者在 main 前进窗口内读到旧值判"未前进"（17:45:10 合并 vs 17:45:48 回执；18:05:50 前进 vs 审查段）。对策=终审排在自己队首时派发，以入队 preflight 的 main_head 为准 |
| 9 | main 直写防护 | 通过：cd+git commit 姿势在他人 live lane 共存时被拦（判定为 main 直写），git -C worktree 姿势通过——姿势即纪律 |
| 10 | 子代理句柄丢失 | 实测 1 次：subagent_result 报"句柄不存在"但子代理实际完成（回执文件存在）——查询失败不等于任务失败，以回执/topology 为权威 |
| 11 | 串行合并的 base 前进 | 通过：C 合并后 A/B stale→rebase（paths 正交零冲突）→重验。第 k 条 lane 承受 k−1 次 rebase+重验——终审时序问题的成本面 |

## 4. 改进建议（沉淀给下一轮）

1. 终审时序：merge-review 应在 lane 成为队首（无前序待合并项）时派发，避免第 8 条的竞态与第 11 条的重复终审。
2. lane 拆分前置查依赖面：私有函数签名（_atomic_write）被 e2e 脚手架 monkeypatch——拆 lane 时把"内部签名依赖面"纳入 paths 考量（本轮以白名单外后果面补入+补审处理）。
3. 门禁增量：rebase 为零冲突纯 replay 且 paths 与前进提交不相交时，全量重验成本（3×10min）高于增量风险——可考虑降级重验通道（需演进提案，本轮按现行纪律全量重验）。
4. 审查-树强绑定的成本：4 行 pyright 修复触发整轮重审。可探索切片内机械修复（类型收窄/格式）快速通道。

## 5. 回执与证据索引

- merge-review 回执：docs/governance/receipts/ 下 merge-review-lane-063c5b32-20261111T173711+0800.json、merge-review-lane-42c4d690-rebase-20261111T180430+0800.json、merge-review-lane-69edeadf-final-20261111T182424.json（另有 1bc4a8fcc80d 早期版）
- verify 凭证：data/audit/verify_receipts.jsonl（lane-063c5b32:fcfb4027、lane-42c4d690:8e78aa58、lane-69edeadf:5c73df7d）
- 全量门禁 exit=0：Lane-C job-45c0a25223474484b390（@8e78aa58e）、Lane-A job-822b655ab7044c7bbb2d（@5c73df7da）、Lane-B job-b262ef5ff4924b8c849c（@7a496abe3=终态 main 同树）
