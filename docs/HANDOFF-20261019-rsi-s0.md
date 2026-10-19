# HANDOFF-20261019 · RSI S0→S1 会话交接

> 用途：本会话过长，后续由新会话接管。**新会话先读本文件，再核现场事实，最后才动。**
> 生成时间：2026-10-19 19:27（+08:00）｜ 生成者：主代理（LFL）

## 0. 一句话现状

S0（方法卡 RSI v1 / P28 假设）正在跑满 120 对，预计 20:10 前后完成；两处统计口径待用户拍板；此后所有代码一律走「GLM-5.3 写码子代理 + 独立 GLM-5.3 审查子代理 PASS 后才可跑全量」。

## 1. 现场事实（19:26 实测，非推测）

| 项 | 事实 |
|---|---|
| 跑批进程 | pid 78271 存活，`--workers 4`，日志 `evals/methodcard_rsi_v1/s0_p28/results/run_full4.log` |
| 规模 | pool=120 × 2 臂 = 240 jobs；本次 pending=225（15 条为早前已完成） |
| 进度 | 80/120 对；`calls.jsonl` 163 条 ok、0 坏行 |
| 速率 | 1.73 对/分钟 → 预计 **20:10 前后**跑满 |
| 兜底 | 已注册 `task_once` 21:00（sched-9df98e37），只做核对、不启动新实验 |
| web 服务 | generation=290 succeeded，desired==observed，git_head 一致（926eb1cea2） |
| schedule.json | 5 条周期条目 `task_mode=task_recurring`，`wake_fires_total/expires_at/workdir/dispatch` 齐全；另有 1 条 task_once（FR-1 T+28d）无 wake 字段，属正常 |
| 迁移日志 | `/tmp/migrate_standing.log` 报 “entry already has a wake grant”（幂等拒绝，非失败）；`/tmp/migrate_daemon.log` 6 次 count=0 后退出。**以 data/schedule.json 实读为准：数据已生效** |

## 2. 中途读数（80/120 对，**非终值**）

| grader | D | R | 净差 | both_pass | both_fail | no_card 通过率 | card 通过率 | 中位字数(nc/card) |
|---|---|---|---|---|---|---|---|---|
| v1.0 | 4 | 17 | −13 | 5 | 54 | 27.71% | 11.25% | 354 / 496 |
| v1.1 | 7 | 15 | −8 | 7 | 51 | 27.71% | 17.50% | 354 / 496 |
| v1.2 | 14 | 13 | +1 | 9 | 44 | 27.71% | 28.75% | 354 / 496 |
| v1.3 | 19 | 11 | +8 | 20 | 30 | 38.55% | 48.75% | 354 / 496 |

**读法（重要）**：整条“卡有效”的信号**只在 v1.3 出现**，而 v1.3 恰恰是唯一放宽 c2 的版本。也就是说，“改进检测器”和“拟合假设”在观测上不可分。这不是可以靠再调正则解决的问题，只能靠 S1 阳性对照（gold vs filler）来分辨「卡无效」与「仪器盲」。

## 3. 两个待用户拍板事项（建议已给出，未执行）

### D1 · gate 口径
- 现状：`run_s0.py:279` `gate_both = all(四版 D≥30)`。
- 问题：v1.0 的 c2 只看末 200 字符，对卡臂有**已知系统性假阴**（80 对里 D=4、R=17，方向是反的）。把坏仪器的低 D 当成更严的闸门，方向错了。
- **建议**：主判据用 v1.3；v1.0/v1.1/v1.2 只做**方向一致性**（各自 D≥R），不再要求同阈值。
- 诚实边界：这是看到中途数据后改口径，属事后调整。缓解三件套：① 现在（终值出来前）就把新口径写死；② 两套口径**并列报告**，不藏旧口径；③ 即便 v2 通过，也只记为「S0 指向性阳性、待 S1 确认」，**不得记为干净 PASS**。

### D2 · S0 FAIL 时是否进 S1
- **建议：进**。S0 的问题是“该仪器能否测出卡的效应”，S0 本身答不了“卡无效”还是“仪器盲”。
- S1（gold card vs filler card）正是仪器灵敏度校准：连已知有效卡都测不出 D≥30，则 S0 的零结果无信息量。
- 前提：T1/T2 完成、check 集冻结、审查 PASS。S1 定位是「校准」，不是「疗效」。

## 4. 后续任务 DAG

| ID | 任务 | 负责 | 状态 |
|---|---|---|---|
| T0 | 跑满 120 对，不早停不改判 | 进程 78271 | 进行中（80/120） |
| T1 | `analyze_s0.py`：四版终值表 + Wilson CI + c3 长度分层 + c2 负向审计 + 两套闸门并列 | 写码子代理 `subagent_03397bd46818`（glm-5.3） | 进行中 |
| T2 | 独立代码审查（只读，PASS/FAIL + P0/P1） | 审查子代理（glm-5.3，待 T1 完成另起） | 未开始 |
| T3 | 终值报告：改 §10.9（c2/c3 两条新证据），两套 gate 结果并存 | 主代理 | 未开始 |
| T4 | 新 check 集（c3 加长度对照；c2 改段落级“先设分叉”；c1 改“引用回执字段”；c4 弃用） | 写码+审查子代理 | 未开始 |
| T5 | S1 阳性对照（gold + filler） | 同上 | 未开始 |
| — | S2/S3、变异器 R3–R13 | **不动** | 冻结 |

## 5. 子代理协议（用户 2026-10-19 新规）

1. 写码一律 `spawn_subagent(model="glm/glm-5.3")`，任务书要给**验收命令**，不给结论。
2. 审查必须**另起独立子代理**、只读、输出 PASS/FAIL + P0/P1（带 file:line）。
3. **审查未 PASS 不得跑全量**（任何花钱的批量 completion）。
4. 主代理只做统筹：定验收、核回执、不代子代理写实现。

## 6. 红线（不变式）

- 不改 v1.3 及以前的正则；不改 pool；不改已写入的 `calls.jsonl`。
- 不早停、不中途改判、不为让数字好看而调参。
- D<30 时措辞只能是「本仪器下测不出」，不能写「卡无效」。
- 任何“完成”必须有对应回执；无回执只报“已发起/进行中”。

## 7. 已踩过的坑（新会话必看）

- `GRADERS[g](text)` 返回的是 **`(checks_dict, status)` 二元组**，不是 bool。写成 `bool(g(text))` 会因“非空 dict 恒真”得到“四版全过”的假结果（本次已实际踩到并纠正）。
- `case_pass` 口径是 `passes=[v for v in checks.values() if v is not None]; bool(passes) and all(passes)`（`run_s0.py:211-217`）。
- 去重必须用 `run_s0.dedupe()`（保留最早一条 ok），不要自写。
- macOS 无 `timeout` 命令，用 python 侧超时或 `gtimeout`。

## 8. 新会话启动清单

```bash
cd <local-user>/Project/llm-first-loop-mirror
ps -p 78271 -o pid,etime,stat           # 跑批是否还活着
tail -5 evals/methodcard_rsi_v1/s0_p28/results/run_full4.log
grep -c '"ok": true' evals/methodcard_rsi_v1/s0_p28/results/calls.jsonl
```

1. 核对上面 3 条，**不要**凭本文件直接下结论（RULE-AI-12：先验证外部状态）。
2. 跑完且 T2 审查 PASS 后，才可 `python3 analyze_s0.py`（离线分析，不花钱，但仍以审查为门）。
3. 把四版 D/R、Wilson CI、c3 长度分层、c2 零标记计数、两套闸门结果**如实**报用户。
4. **不要**自行启动 S1、不要动 S2/S3、不要改 schedule 其它条目。
5. 等用户对 D1/D2 拍板。

---

## 新会话接续记录（2026-10-19 19:36 起）

- 旧会话的 T1/T2 子代理均已 `cancelled`，经事件日志核对为零写盘（只读 ls / read_file / python 只读），未产出 `analyze_s0.py`，未产出审查报告。
- 本会话重启：
  - T1 写码：`subagent_c27cfceb7099`（glm-5.3），唯一交付物 `analyze_s0.py`，已给验收命令（run_s0.summarize 交叉核对、Wilson 自检、确定性、只增文件）。
  - T2 审查：`subagent_ddec88b0fda2`（glm-5.3，只读），审 `run_s0.py` + `build_pool_p28.py`，裁决 `VERDICT` 与 `ROUND USABLE`，报告写 `docs/REVIEW-S0-HARNESS-20261019.md`。
- D1 已冻结：`evals/methodcard_rsi_v1/s0_p28/GATE-AMENDMENT-v2.md` + `GATE-AMENDMENT-v2.FREEZE.json`。冻结时点 19:35:54，四版共同配对 92/120；主判据 v1.3 D≥30 + 旧三版各 D≥R；只记 `S0 directional positive — pending S1`，禁止 S0 PASS；旧口径 `gate_both` 并列报告。
- D2 已接受：S1 必须执行，定位为解释 S0 的仪器校准前提；前置=check 集冻结 + 独立审查 PASS。
- 进程 78271 未杀，继续跑；**结果可用性挂在 T2 的 `ROUND USABLE` 上**：若 T2 出 P0 使 D/R 不可信，该轮作废重跑（约 2 小时）。
- 21:00 兜底 `task_once` 仍在；新会话到点只核对，不启动新实验。
