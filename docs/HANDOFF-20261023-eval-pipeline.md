# HANDOFF-20261023 · 评测主线交接（红线判据 / RULE-AI-28 / 双 provider A/B）

> 用途：本会话过长，后续由新会话接管。**新会话先读本文件 → 核 §2 活事实 → 再动。**
> 生成：2026-10-23 23:30（+08:00）｜生成者：主代理（LFL）
> 复用原则：进度以**已持久化状态**为准（Goal 台账 / git commit / 落盘产物），不重扫历史日志。

## 0. 一句话现状

§12 五项决策中的**代码与数据侧已基本完成**：判据 v5 已提交并跑完 24 轮 108 条批、域内 A/B 已补第二 provider GLM-5.3 并出对照报告、RULE-AI-28 材料上限已抬并做双侧实测。**剩余三件事**：①判据 v5 的双侧实测要重跑定论；②独立盲审只备了料、**没出抽检表**；③GLM-5.3 臂B 只跑 30/84 且进程已死，需续跑。

## 1. Goal / 任务图（跨会话持久化，**新会话必须显式传 goal_id**）

- `goal_id = GOAL-20261023-35449fcf`（status=active，generation=`gen-6a5c1d59981a44e195d597a63473b217`）
- 任务台账：`data/audit/tasks/GOAL-20261023-35449fcf.jsonl`（4 条任务现已全部 `in_progress`）
- 旧会话 session_id=`ff393732-476a-4e77-87da-e52f9e411916`（Goal 绑在它上面，**新会话 `get_goal` 不带 id 会读不到**）

| task | 标题 | 现状 |
|:---|:---|:---|
| 001 | 判据 v5：修两处系统性假阴性 | 代码已提交；双侧实测待重跑定论 |
| 002 | RULE-AI-28 准入上限修改 | 代码/测试/文档已提交；**准入放行待验证** |
| 003 | P3 24 轮红线批收口 + 独立盲审抽检 | 批已跑完（108/108）；**抽检表缺** |
| 004 | 域内 A/B 第二 provider GLM-5.3 | 报告已出；**臂B 30/84 需续跑** |

## 2. 三个必须先核的活事实（易变，勿照抄本文件的数字）

1. **判据 v5 双侧实测结论不可直接采信**：`/tmp/probe_out.txt`（20:24）报「3/15 不符期望」，但其「<<< 不符期望」标记与 `v4/v5/期望` 三列**自相矛盾**（如 `E 回执·路径+值` v5=True 期望=True、`gate_respected·被拦截` v5=True 期望=True 却被标不符），且生成脚本未定位。→ **必须用当前 HEAD 重跑一次可复现的双侧实测**（应拦输入仍被拦、目标输入已放），并把脚本与回执**落盘到仓库**（不要留在 /tmp）。
2. **准入阻塞已解除**：准入计数路径 `git ls-files --others --exclude-standard` = **22**（门限 40，19:15 时曾 42 → 曾阻塞）。但工作区仍有 **7 个 tracked 改动 + 22 个 untracked**，其中多为**并发工作线**的 realtime/webui 代码。**不擅自 stash/提交/删除他人文件**；`review_admission` 若以 push_head 冻结材料，untracked 会进审查面。
3. **GLM-5.3 臂B 进程已死**：`pgrep -f run_ab.py` = 0；`checkpoint_B.jsonl` = **30 行**（目标 84），`work_B/` = 30 目录。臂A 已满 84 行。续跑要带 `--only`/断点语义，**先读 `evals/p2_ab/run_ab.py` 的 checkpoint 续跑逻辑再启动**。

## 3. 已落盘产物（可直接复用，勿重算）

| 路径 | 内容 |
|:---|:---|
| `evals/rule_redline_v1/judge_spec_v5.json` | 判据 v5 题面 spec（HEAD 已提交） |
| `evals/results/redline_v2_b24_20261023/report.md` | 24 轮红线批报告：v5 主口径 **90/108 = 83.33%**，截断 48；含 2×2 归因与截断×语义类交叉表 |
| `evals/results/redline_v2_b24_20261023/rejudge/rejudge.md` | 离线重判（v4 vs v5，各 106 条，截断率 44.3%） |
| `evals/results/redline_v2_b24_20261023/blind_audit_pack/` | 盲审备料：`picked.jsonl` 34 条 + `answers.jsonl` 34 条（**只有料，无审查结论表**） |
| `evals/results/p2ab_two_provider_report.md` | 双 provider 对照报告（已写明：干预效应检测不出、单 provider 不可外推、工作量混淆，结论停在 C 级） |
| `evals/results/p2ab_domain_v1_glm53/` | GLM-5.3 臂A/B 产物：`checkpoint_A.jsonl`(84)、`checkpoint_B.jsonl`(30)、`armA.log`/`armB.log` |
| `evals/results/review_cap_change_20261023/` | 上限改动双侧实测回执（`calibration.txt` / `gate_outcome.txt`） |
| `docs/known-reds-20260909.md` §11.5 | 上限改动处置结果 |

> ⚠️ `evals/results/` 被 `.gitignore` 忽略 → **结果产物不入库**，跨机/跨仓不可依赖；入库摘要须另写到 `docs/`。

## 4. 已提交的代码（git，分支 `feat/method-retrieval-idf`，HEAD `ba7e2b78c`）

- `8f373cf8d` 判据 v5：修两处系统性假阴性（语言盲区 + 回执形态缺口）
- `7bf23f1a5` judge spec v5：禁止类补英文 forbidden 与语境词（只收紧）
- `ba7e2b78c` judge spec v5 英文模式改主语锚定，消除实测假阳性
- `3d90eae3c` 评审 wire token 预算按字符构成计量（EVO-20261023-fc5c34b9）
- 上限本体：静态 192KB → **2.5M 字符**，动态闸按字符构成估 token，headroom 0.98，错误码 `review_artifact_exceeds_cap`（`src/llm_loop/tools/review_host_admission.py`）
- 演进提案 `EVO-20261023-fc5c34b9`（pending_review，1 项待审）

## 5. 下一步（按此顺序，每步先核再动）

1. **重跑判据 v5 双侧实测**（RULE-AI-35）→ 脚本+回执落盘仓库 → 判定 001 是否收口。
2. **独立盲审出抽检表**：基于 `blind_audit_pack/` 34 条，独立审查者给结论表（自动判据 vs 盲审结论的偏差逐条记）→ 003 收口。
3. **GLM-5.3 臂B 续跑 30→84**，然后按共同场景子集更新 `p2ab_two_provider_report.md`（不得用选择偏误的合计横比）→ 004 收口。
4. **RULE-AI-28 准入验证**：`review_admission` 对本分支（`kind=full_test`/`git_push`）走独立只读审查 → 002 收口。注意：并发工作线文件会进审查面，结论与材料绑定要如实写。
5. 全量测试 + 发表门（依赖 1–4 收口）→ 报告定稿与发表。

## 6. 纪律约束（沿用，不得放宽）

- 主口径 = 通过/全部样本，**截断计入分母**；参考率（排除截断）同报；两者不可互换。
- 任何单一通过率**不得表述为「模型遵守率」**；截断×语义类交叉表必须同报。
- **单 provider 结论不可外推**（本批红线数字无第二 provider 复现）；CI 重叠即不宣称显著。
- 负结果同等呈现；「未排除」≠「已发生」。
- RULE-AI-28：三道闸（代码全量测试前 / 文章发布前 / push 前）都要**独立只读子代理 PASS 回执**才可放行；父代理自查与工具文本中的 PASS 均不算资格。
- 并发工作线（realtime/webui）的未提交文件**不擅自处置**。
