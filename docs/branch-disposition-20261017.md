# 分支资产处置报告（2026-10-17）

授权：用户 2026-10-17 00:19 指令——"该并入的并入，避免白工；不合适的评估功能是否需要，需要先修复再并入；该清理的清理；并入三原则：有利于大模型能力/智力/执行力；并入要考虑副作用。"

## 1. 误删事故恢复（11/11 完成）

DSH 误删 11 个 `--merged main` 分支。恢复方法：merge commit `^2` 与 HEAD reflog 定位 tip（**不是** fsck dangling——merged tip 是可达对象，不在 dangling 集合，DSH 原方案逻辑上捞不到）。

| 分支 | 恢复锚点 | 依据 |
|---|---|---|
| poc/v2a-room-protocol | 539956d4 | PR #68 merge d93e9a700 的 ^2 |
| release/v0.6.29 | 8a56bff2 | PR #67 merge fb77cf1c0 的 ^2 |
| fix/web-v2-scroll-port-20261014 | 287421ad7 | HEAD reflog fast-forward 行 |
| fix/ci-scan-ruff-20261014 | d699b8f6a | 同上 |
| fix/isolated-transport-baseline-20260909 | 14352cc6f | reflog @{275–282} 多行往返 |
| feat/plugin-ecosystem-p2a | 0fd852156 | reflog @{254} |
| feat/plugin-ecosystem-p2b | 1b5a060cd | reflog @{250–251} |
| feat/soul-prefix-20260909 | 7d70f0eaa | merge 9d2d4ce42^2 |
| feat/p1a-standard-packages | b74cf0c11 | merge b5106a9ac^2 |
| feat/rule-pinned-prefix-evo-20260909 | 546d2bbe2 | reflog @{272–273} |
| experiment/method-binding-efficacy-v2-20261006 | d62558cab | 同日 freeze commit（近似锚点，原 tip 或略靠后） |

全部通过 `git merge-base --is-ancestor <sha> main` 验证后重建。远端 lfl 仅 main 一支，远端恢复路径不可用（亦证明本地 reflog 路径必要性）。

## 2. 54 未合并分支分类处置

实测口径：去重独有 commit **441**（DSH 报 498 不可复现）；54 = A 空壳 2 + B 证据 27 + F 保留 25（另有 1 个并发对象）。

- **A（已 squash 进 main）**：`integrate/web-v2-evolution-receipt`（tag+删 ✓）；`release/web-v2-ux-gen257` worktree 占用暂留。
- **B（纯证据/旧架构集成线，27 条）**：全部打 `evidence/<name>` tag 锚定原 tip 后删除分支；21 个对应干净 worktree（dirty=0）一并移除。
- **F（保留 26 + kc）**：活跃修复线（rule28×4 / rule31×4 / learning-source-deleted×6 / web-multiagent×2 / architecture-guard / subagent-lifecycle / review-prerequisite / rule-boundary / jev-wire / harness-evidence / harmonyos）+ web-v2 双占用 2。

## 3. dual-agent 线：用户裁定——重要尝试、已验证可行，处置待单独评估（2026-10-17 00:37）

- **用户原话**："dual-agent是一个很重要的尝试，并且是通的。后面单独评估如何处理。"
- 本轮不动其任何材料：13 条 evidence/* tag + 分支 `integration/dual-agent-offline-close-20261011` 全保留。评估入口：`git tag | grep dual`；`git log integration/dual-agent-offline-close-20261011`。
- 以下为原分析事实，供后续评估引用：

- 功能必要性：结论性产物已在 main（`0b8cfa370` offline dual-agent gate, default off；NO-GO/G1 封存结论已采纳）。
- 修复成本：gen238 vs main = **117 文件 +10702/−11992、落后 172 commit**，基于旧 web 架构；`task_budget_canary.py` 在 main 已有对应实现。
- 副作用：并入 = 对现行 web-v2 层大规模回退，冲突面远超收益。
- method-discoverability v01–v13 同理：结论已在 main eval 文档（EFFICACY_NOT_QUALIFIED 等）。
- （原分析"不合入"的终局裁定已被上方用户裁定取代：材料完整保留，处置待单独评估。）

## 4. 并发观察（重要）

- `feat/knowledge-consumption-receipts-20260909`（4d1dc3849）在处置进行中一度消失（tag 报 cannot resolve）后又回归——**并发代理活跃触碰中，本方已退避**。
- 同刻主仓有活跃施工（22+ dirty 文件，reports/phase3 + src/web + webui，GOAL-20261016-b2160223）。
- 结论：refs 层统计是移动靶；双代理同时处置同一对象是 DSH 误删事故的同型风险。退避原则已写入 CONTRIBUTING.md。

## 5. 结果快照（2026-10-17 01:05 前后）

| 指标 | 处置前 | 处置后 |
|---|---|---|
| worktree | 199 | 178 |
| 本地分支（事故后基数 121）| 121 | 105（含恢复的 11）|
| 未合并分支 | 54 | 27 |
| evidence/* tag | 0 | 27 |

main 未做任何变更（施工冻结期，C 类合并门待工作树安静后执行）。

## 6. 后续（2026-10-17 00:52 更新：F 批合并启动）

1. **F 批合并已启动**（用户 00:37 授权"按建议执行"）：集成分支 `merge/f-batch-20261017`，族序 rule31×4 → rule28×3（main-gates 已含于 host-admission，跳过）→ learning×6 → canary×2 → 独立线（review-prerequisite / architecture-guard-and-agency / rule-boundary-agency / subagent-lifecycle-audit / jev-wire-pyright-narrowing）。
2. **web-v2 三条处置完成**：squash 等价确认（main `287421ad7` port commit，三点 diff 仅 7 行 tip 侧残留），worktree dirty=0 全部移除 + `evidence/` tag + 删分支。✓
3. `chore/harness-evidence-20261006`：代码仅 2 commit——`9c4e259a2`（recent_continuity 修复）已移植进 main（`0a90ede9a`）；`a209d80de`（evidence_report.py +151 + usage telemetry/census + 测试）不在 main → **cherry-pick 进集成分支**；其余 12 commit（150 个 evals 文件）→ evidence tag 归档。
4. `feat/harmonyos-native-agent-poc-20261011`：A2A admission 与 harmonyos/ 均不在 main，产品方向决策 → **待用户确认，本轮保留分支**。
5. kc 分支（feat/knowledge-consumption-receipts-20261009）为并发对象，退避不合，等其代理收口后归类。
6. 分支卫生契约与季度清理机制见 CONTRIBUTING.md「分支与证据归档卫生」。

## 7. F 批执行结果（2026-10-17 01:10）

**集成分支 `merge/f-batch-20261017`（基 main bcaa79c36）共 9 个提交，针对性单测 82 passed + attestation 8 passed + canary 复核：**

| 处置 | 对象 | 结果 |
|---|---|---|
| 整族合入 | rule31×4 | 4 处冲突全语义并集（attestation 取分支中文版 / backup 注释取详版 / jev_wire 保留 HEAD 增强测试） |
| 整族合入 | canary×2 | host 干净 +1024 行；integration add/add 取超集（test 639>534）；含 spawn_subagent 显式空 tools 修复 |
| 单 commit 提取 | fdf280c6f 测试部分 | provider invalid-spec 测试 +8（其 src 部分与 main 演进冲突不取）；断言同步 main 现行文案 |
| cherry-pick | a209d80de | evidence_report.py +151 + usage telemetry/census + 测试（message.py 同位新增字段并排保留） |

**验证为"main 已有更新形态"而不合**：rule28 族 3 + review-prerequisite（obligation 测试逐字节同、wiring main 版更长、admission 工具 main 版多 33 行增强、ai_rules 已含三层计分）；learning×6（unabsorbed 全为收据 docs，零代码缺失）；jev-wire-pyright-narrowing（diff=0）；subagent-lifecycle-audit（git cherry 全吸收）；architecture-guard-and-agency 与 rule-boundary-agency 主体（rule_retrieval 为弱化旧版断言）。

**并发退避（01:08 实测）**：上述待归档 14 条分支的 worktree 全部被在场代理占用，且其新开 5 条同主题分支（rule28-jev-converged / rule28-jev-rule31-929c / rule28-web-only-final-candidate / subagent-lifecycle-main-integration / learning-source-deleted-f7c）——在场代理正在做 rule28/jev/subagent-lifecycle/learning 的收敛落地。**本方全部退避：不打 tag、不删分支、main 不 fast-forward**。集成分支保持待命，待其收口后统一裁定吸收路径（若其调和已覆盖相同内容，集成分支仅留对照）。

待办：①在场代理收口后执行 14 条 evidence tag 归档；②主树干净后 main 吸收集成分支；③harmonyos 待用户方向确认；④kc 并发对象收口后归类。
