# QUALIFICATION 2026-09-16 — Peer Scorecard v0.1

> 范围：把一份外部（GPT 产出的）"六维等权 10 分制"竞品评分，替换为一个可复现、可在第三方机器上重跑的测量协议，并在**正确锚点**上重跑。
>
> 非目标：不决定任何产品优劣，不决定下一步开发优先级，不进入 runtime/CI/release 门禁。
>
> 结论一句话：**subject 列（LFL）现在可机械复现；counterparty 列在现有证据下不可评分**——36 个格子里 0 个达到可出数字的证据层。

## 1. 证据边界

本文件只声明本轮实际验证过的事实，分三层：

1. **机械可复现**：LFL 侧 33 个 anchor + 6 个 counter-anchor 在固定 commit 的**已提交树**上逐一校验（tier `V`）。
2. **取证但未逐字**：counterparty 的 7 个 cell 只有 URL + 抓取日期 + 转述（tier `T2`/`T3`）。
3. **未取证**：counterparty 其余 29 个格子为 `unknown`，不是"低分"。

已明确**不**主张：任何跨产品的能力排名、任何"谁领先多少"的量化结论、任何 vendor-symmetric 的对比。

## 2. 冻结工件

| 工件 | 路径 | SHA256 |
|---|---|---|
| 机器合同 | `docs/analysis/PEER-SCORECARD-v0.1.json` | `4d63a512647d8c7826ce1cd13b97a6e5a25dd8a5208decf16594b3407b8487b0` |
| 只读 runner | `scripts/qualification/peer_scorecard_v0_1.py` | `74757ebe323bbc908512a69cc73605a4c3fd3a3be7c2dd2805542eb9f92b7121` |
| 确定性 TDD | `tests/unit/test_peer_scorecard_v0_1.py` | `2de27c2c92a439b29191fd58e926fe7bd3c2feed326fd06db3106ef74da9a96c` |
| 冻结协议 | `evals/peer_scorecard_v0/PROTOCOL.v0.1.md` | `4901c37cf9e5facb155f29d36b002307e46ada59116c62323b002127d2b3a95d` |
| 首轮报告 | `evals/peer_scorecard_v0/results/scorecard-20260916-832b4dfa.json` | `5bf4493b1df00daa0d761dda760f670c7f6d7a9887c1ab7ebd7207be8c7c001e` |

subject 锚点：`832b4dfaa2d6dba8143bd91239aa0b22b8f8dbf9`（2026-09-16T16:32:27+08:00，分支 `evo-20260914-exec-surface-followup`）。

runner 是显式调用的 qualification 工具，**不是** runtime hook、CI 准入规则或提交门禁。非零退出只表示"冻结合同与当前 checkout 不再一致"。

## 3. 被判废的旧表的三条硬伤（机械可判）

旧表的数字在本协议下会在三条独立规则上同时失效：

1. **没有任何 evidence tier**：全部数字是无来源 prose（`T4`），而 `T4` 按合同不得携带数字。
2. **锚点与叙事互斥**：旧表自称按 `integration/convergence-20260911@2d247ba7` 计分，但该 ref 的提交时间是 **2026-09-13T21:52:11+08:00**，且正文同时把 9/12、9/13 的工作计入。
3. **跨证据层等权平均**：subject 列是代码可核验事实，counterparty 列是 prose 印象，两者被平均进同一个数。

## 4. 锚点漂移的量化结果

把同一份冻结合同指向旧表自称的锚点 `2d247ba7`，runner 直接判该 checkout 不满足合同：

```text
contract/provenance violations:
  - D3_context_recovery [d3.run_integrity_receipt]: anchor drift:
      src/llm_loop/runtime/causality.py: def build_run_integrity_receipt
  - D4_runtime_reliability [d4.build_identity]: source missing in committed tree:
      src/llm_loop/runtime/build_identity.py
[runner exit: 1]
```

逐维 rung 对比：

| 维度 | rung @ `2d247ba7`（旧表自称锚点） | rung @ `832b4dfa`（本协议锚点） |
|---|---:|---:|
| D1 long-horizon autonomy | 3 | 3 |
| D2 concurrency / isolation | 3 | 3 |
| D3 context / recovery | **0** | **4** |
| D4 runtime reliability | **1** | **4** |
| D5 observability / governance | 3 | 3 |
| D6 ecosystem / UX | 3 | 3 |

归因（`git merge-base --is-ancestor` 实测）：

- `src/llm_loop/runtime/build_identity.py` 由 `9bdc241e`（"expose exact development build identity"，9/13）引入；
  **`9bdc241e` 不是 `2d247ba7` 的祖先**，但是 HEAD 的祖先。
- `def build_run_integrity_receipt` 由 `aec9487a` 及其并行分支提交引入，同样不在 `2d247ba7` 上。

也就是说：旧表在一个**没有 build identity、没有 run integrity receipt** 的 revision 上给出了
Context/Recovery 9.8 与 Runtime 9.4，而它的正文恰恰把这两项 9/13 能力描述为已计入。
这不是精度问题，是**锚点与叙事取了不同的分支线**。

## 5. 本轮测量结果

```text
subject   : lfl @ 832b4dfaa2d6 (2026-09-16T16:32:27+08:00)
resolution: committed_tree (working tree is not read)

dimension                          rung unsup  anchors  counters
D1_long_horizon_autonomy              3     4   5/5     cross_process_coordinator=open
D2_concurrency_isolation              3     4   5/5     execution_workspace=open,worker_lease=open
D3_context_recovery                   4     -   6/6     -
D4_runtime_reliability                4     -   5/5     -
D5_observability_governance           3     4   6/6     control_plane_view=open
D6_ecosystem_ux                       3     4   6/6     acp_adapter=open,adoption_telemetry=open
                                   (not measurable from this repository)

counterparty cells: 7/36 declared, 29 unknown, eligible for a number: 0
tier histogram    : {'V': 0, 'T1': 0, 'T2': 6, 'T3': 1, 'T4': 0}
cross-vendor composite: not_evaluated
```

读法（重要）：

- **rung 是已声明证据的下界，不是能力刻度。** rung 不可跨维度比较，不得平均。
- `unsup` 是不可达的下一级 rung：它是**证据缺口**，按合同不得读成"能力缺失"。
- D1/D2/D5/D6 停在 3 是因为各自声明了 counter-anchor（`coordination/`、`execution_workspace/`+`worker_lease.py`、`web/agent_tree.py`、`acp/`+`ADOPTION.md`）实测**不存在**。它们由程序机械判定为 `open`，而不是由人打分。
- D6 额外标注 `in_repo_measurable=false`：分发/采用在本仓库**没有任何可观测事实**，该维 rung 只能界定"已声明的接口"，不能界定该维度本身。
- workstation 有 62 项 dirty（含未跟踪目录），**不影响结果**：锚点走 `git show <commit>:<path>`，从不读工作树。这是与 `scripts/qualification/agent_qualification_envelope_v0_1.py`（读工作树）的刻意差异。

## 6. counterparty 列的实测结论

- 36 个 (product × dimension) 格子里只有 **7** 个进了取证清单，**29** 个是 `unknown`。
- 达到可出数字门槛（`T1` 逐字引用 vendor 页面）的格子：**0**。
- 因此 `cross_vendor_composite = not_evaluated`，这是**合同强制**的结果，不是本轮偷懒。

要让任一 counterparty 维度可评分，唯一路径是补 `T1`（逐字 + URL + 日期）。在补齐之前，
"Cursor 9.73 / Claude Code 9.70" 这类数字在协议内无法生成，也无法被第三方重算。

主观判断仍然允许，但只能进 `declared_judgment_cells` 通道，每格必须带 `judge` / `judged_at` / `rationale`，
且**禁止**携带 measured rung。v0.1 该通道为空。

## 7. 明确不做的事

- 不新增任何 score/verdict 到 runtime 或 CI。
- 不改 `src/` 任何一行；本轮只有 docs + 只读脚本 + 测试。
- 不把 rung 当成 roadmap 排序依据。外部分析给出的 P0 顺序（Project/Coordinator + ExecutionWorkspace）
  与本仓库 `docs/analysis/AUDIT-20260907-lfl-vs-peers.md` §5 已冻结的 CK6/CK8 顺序不一致
  （CK6 明确"在 continuity 内核稳定后再做，不与 CK1~CK5 并行"；CK8 明确"最后再投入跨 harness 高成本对比"）。
  哪一套顺序成立是模型/人的判断，**本轮协议不裁决**。
- 不为过测而放宽任何阈值；`band_requires_tier` 的收窄/放宽需要新协议身份 `v0.2`。

## 8. Gate 与验收

focused gate（本轮全部通过）：

```bash
.venv/bin/python -m ruff check scripts/qualification/peer_scorecard_v0_1.py tests/unit/test_peer_scorecard_v0_1.py
.venv/bin/python -m ruff format --check scripts/qualification/peer_scorecard_v0_1.py tests/unit/test_peer_scorecard_v0_1.py
.venv/bin/python -m pytest tests/unit/test_peer_scorecard_v0_1.py -q
.venv/bin/python scripts/qualification/peer_scorecard_v0_1.py
```

- ruff check / format：通过。
- 新 TDD：**30 passed**，覆盖 4 类真实验收：合法合同通过、锚点漂移被拒、工作树专用路径被拒、低于出数层携带数字被拒。
  其中 `test_rejects_cited_tier_missing_provenance_fields` 在实现阶段**真的抓到了一处漏洞**：
  首版 `_validate_cell` 只对 `V`/`T1` 校验 URL/日期/claim，`T2`/`T3` 丢了引用却不报错。修的是实现，不是测试。
- runner 在冻结锚点上 exit 0；指向 `2d247ba7` 时 exit 1 并给出精确漂移位置。

## 9. 下一步（需另行授权）

1. 若要恢复 counterparty 可比性：按 `T1` 标准补逐字取证，逐维补齐，补齐前该维对**所有**产品都无数字。
2. 若要引用"缺口即优先级"：counter-anchor 已把缺口机械列出（`coordination/`、`execution_workspace/`+`worker_lease.py`、`web/agent_tree.py`、`acp/`），可直接作为设计输入，但仍需过 A.5 G1–G4。
3. 任何把本协议接成阻断门禁的改动，都是**新增控制机器**，需要独立的 A.5 声明与 qualification。

---

# 附录 v0.2 — 评分比较视图（独立协议身份）

> v0.2 是**新协议身份**，不修改、不重释、不覆盖 v0.1 证据。
> v0.1 合同在本轮前后 SHA256 均为 `4d63a512647d8c7826ce1cd13b97a6e5a25dd8a5208decf16594b3407b8487b0`，
> 由 `test_v01_contract_is_untouched_by_the_v02_extension` 机械守住。

v0.1 以 `cross_vendor_composite = not_evaluated` 收口。"把两列摆在一起看"是合理诉求，
但用"悄悄把扣下的数字填回去"来满足它，就等于把整件事的意义抹掉。所以 v0.2 增加的是一个**视图**，不是一个分数。

| 工件 | 路径 | SHA256 |
|---|---|---|
| v0.2 机器合同 | `docs/analysis/PEER-SCORECARD-v0.2.json` | `b491d548f9ac14543072d471ef60ef81c705961e40b4ee0e1de3e06e010b0809` |
| runner（同一实现，两个合同身份） | `scripts/qualification/peer_scorecard_v0_1.py` | `5350083a02b9faa218f3288dbfdd5c50c1a37bb970ca65b8b05ce34608456db4` |
| 确定性 TDD（44 例） | `tests/unit/test_peer_scorecard_v0_1.py` | `437c21cf178c402e50243170b6db32ca2be57c2484b5a08e0af94e7302c4d397` |
| v0.2 冻结协议 | `evals/peer_scorecard_v0/PROTOCOL.v0.2.md` | `715b84ed9a86c25d2a0fb6c1bd4cbfa573fbbce927d85f39052263e894c468b3` |
| 比较视图报告 | `evals/peer_scorecard_v0/results/comparison-20260916-832b4dfa-v0.2.json` | `223718a779a73bfe31d5ebdbd7aa06178f97abea91e89b1e63ed6fd7bfd23b5c` |

## A.1 三通道并排（不合并）

```text
comparison (columns are never averaged together)

dimension                        jdg  rung   antigravit  claude_cod       codex  copilot_ag      cursor   openhands
                                   B     A            C           C           C           C           C           C
D1_long_horizon_autonomy         9.4     3       9.4/--      9.7/--      9.8/--      9.7/--      9.9/T2      9.5/--
D2_concurrency_isolation         9.2     3       9.4/--      9.5/--      9.8/T2      9.5/--       10/T2      9.7/T2
D3_context_recovery              9.8     4       9.4/--      9.9/--      9.6/--      9.4/--      9.7/--        9/--
D4_runtime_reliability           9.4     4       9.5/T2      9.8/T3      9.4/--      9.5/--      9.6/--      9.3/--
D5_observability_governance      9.8     3       9.2/--      9.8/--      9.3/--       10/T2      9.3/--      9.7/--
D6_ecosystem_ux*                 7.8     3       9.5/--      9.5/--      9.6/--      9.9/--      9.9/--      9.4/--
```

- **A** = subject 实测 rung（tier `V`，已提交树核验，是下界）
- **B** = declared judgement（记录下来的主观判断，tier `T4`，**永不**与 A 合并）
- **C** = `旧表判断值/证据层`；`--` 表示该格没有任何已取证来源
- `*` = 该维度在本仓库不可测

## A.2 旧表算术：是对的

runner 从 42 个 judgement cell 重算全部 7 个 composite：

```text
legacy composite arithmetic:
  cursor         claimed  9.73  computed  9.7333  cells  6  ok
  claude_code    claimed  9.70  computed  9.7000  cells  6  ok
  copilot_agent  claimed  9.67  computed  9.6667  cells  6  ok
  codex          claimed  9.58  computed  9.5833  cells  6  ok
  openhands      claimed  9.43  computed  9.4333  cells  6  ok
  antigravity    claimed  9.40  computed  9.4000  cells  6  ok
  lfl            claimed  9.23  computed  9.2333  cells  6  ok
  (all published composites reproduce from their own cells)
```

**这是本轮最需要记住的一条：旧表的除法没有错。** 7 个 composite 全部两位小数可复现。
缺陷从来不在算术，而在于：

1. 42 个输入格**没有一个**带来源（tier 全为 `T4`）；
2. subject 锚定的 revision 与它自己的叙事不一致（见 §4）；
3. 36 个 counterparty 格里只有 7 格有任何已取证来源，**0 格**达到可出数字的逐字层。

也就是说，旧表的可信度问题**不是"算错了"，而是"输入不可复现"**。把算术验证通过误读成
结论可信，正是本协议要挡住的错误。

## A.3 A 列与 B 列不可比

`rung` 是证据下界（0–4 的离散阶梯），`jdg` 是 0–10 的主观判断。两者是**不同种类的量**，
相减、平均、或据此判断"LFL 落后多少分"都是无效操作。v0.2 把它们并排放，正是为了让这个
不可比性可见，而不是把它藏进一个复合数字里。

## A.4 v0.2 相对 v0.1 的验收增量

- TDD 从 30 例增至 **44 例**，新增覆盖：v0.1 字节未被改动、42 格 judgement 完整性与归因、
  composite 算术重算、三通道不合并（含"行内不得存在 merged/composite 字段"）、
  越界 `judged_value`、非数值 `judged_value`、未知 subject/dimension、缺失 cell 的 composite、未知 schema。
- runner 在 v0.1 合同上仍 exit 0（向后兼容），在 v0.2 合同上 exit 0 并输出三通道视图。
- `src/` 仍未改动一行。

## A.5 v0.2 明确不做的事

- 不把任何 `T2` 转述升级为 `T1` 引用——转述不会因为被放在引用旁边就变成引用。
- 不产出跨通道复合数。要让 counterparty 列变成可比较的数字，唯一路径仍是补 `T1` 逐字取证，
  那是**新协议身份**，不是改 v0.2。
- 不裁决"谁领先"。见 A.3。

