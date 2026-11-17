# LFL 多 Agent v1.9 实施收口附录（不改变冻结设计）

- 冻结正本：`DESIGN-20261116-LFL-multiagent-convergence-v1.9.md`，SHA-256 `5e879243f09d0559b706189a1044cd6acf201352ce0c2e865e08095a9e41a4ea`；原件字节不改，不产生 v2.0。
- 旧独立 Reviewer：2026-11-16 23:22，DeepSeek-v4-Flash，会话 `27812a0e-44de-4c70-bfb4-dd546d86f48e`，**REVISE P0=0/P1=2/P2=3**。该结论不能重命名为 PASS；本附录仅登记实际实现、待验收及明确 HOLD。
- 主开发：GPT-6；LFL 原生受管协调 `GOAL-20261117-94401f33` / `lane-067ce5bb`，仅一条隔离写 Lane。MCP Console 原 Goal `fbc69455-667a-409c-8456-af428720208c` 继续有效，最终门禁全通过后才关闭。

## B1 已有能力与待收口差额

- 已进入主线：M1/M3/M4-A（PR #42），受保护 main 的 Host premerge/CI 身份门、单集成写者（PR #51/#52/#53/#55 等）。这些不是「所有多 Agent 功能已上线」的证据。
- **M2-A 未收口**：`feat/lane-cross-goal-m2a-20261116` 的 `97c7a6763` 有 strict flock、跨 Goal 路径锁内冲突拒绝、配置接线和 730 行测试，但当前 `main` 未包含这些改动。涉及 `config.py`、`factory.py` 的路径仍有其他在途 Lane 占用；不得绕过归属抢写。
- 当前 Host gate 对候选变更采用受保护 main blob 一致性和独立签名快照；并不自动允许自身升级。任何未授权的门禁升级继续 **HOLD**。

## 旧 P1-1：有效门禁语义闭包与执行侧身份

- 隔离实现：`scripts/premerge_host.py::_GATE_PATHS` 扩展到 `tests/conftest.py`、`uv.lock`、privacy workflow、额外 CI 脚本；`_verify_gate_closure` 读取受保护 main 的 CI/workflow/shell，发现未钉住的新直接脚本即拒绝；`_verify_host_execution` 要求实际运行目录为干净、精确 `main` checkout，并独立测量运行中的 Host/CI gate 文件 blob 对比 GitHub 可信 main。
- 负测：同 PR 修改辅助脚本/配置、未列入闭包的 CI 脚本、脏/旧执行树、运行脚本 blob 不匹配均拒绝。既有 Host/CI 负测保持通过。
- 边界：脚本内自检是受信任 Host launcher 的纵深防御，不构成对恶意替换了整个入口的全域物理防护；该代码**尚未经过精确 SHA 独审、完整 R9、PR/CI、受控合并与生产验证**，不得标为上线。

## 旧 P1-2：首次后门禁升级与人工授权

- **当前安全事实**：已有 `gate_version_untrusted` 会拒绝候选改写门禁和策略；不允许用自然语言或 PR 评论代替签发器。没有经过受管独立授权的门禁升级不得执行。
- **明确的升级准入合同**：未来升级必须由候选树之外的 Host-owned 签发器产生不可伪造的 `gate_upgrade` 回执，至少绑定 `{repo, base_main_sha, pr_number, head_sha, gate_closure(path->blob), new_policy_sha256, reviewer_child_id, approved_at, approver}`，且绑定精确候选独立 Reviewer PASS、原版 R9 exit0、远端 CI 与 operator 的真实确认。Host 仅以受保护信任根验证该回执，缺失、过期、字段不符、来源不可信一律 HOLD；升级后必须从新的受保护 main 回读新 pin。首次 bootstrap 不得再次使用。
- **未完成项**：当前安装的 Host issuer 尚未提供 `gate_upgrade` 签发与验证入口；本批不借旧签发密钥自行签发、不手写 audit receipt、不绕过现有 Host gate。实现与 macOS 管理员受管验收仍需独立安全门禁，因此 **P1-2 尚未达到生产 PASS**。

## B2：只读动态基线影响判断

- 新增 `baseline_impact.py`，Host 本地 `origin/main` / checkout 分离；NUL 路径、rename 禁用、mode/二进制/merge/脏树/不完整路径/契约提示保守拒绝；main 前进不等于合并资格，rebase 后仅复用现有 `assess_rebase_replay` 并建议受管 carryover，不签发凭证、不复用旧 SHA Reviewer。
- `lane_queue_status(with_impact=true)` 默认关闭、最多 20 项、只读展示 `current/affected/unknown/stale_needs_refresh/carryover_candidate`；caller-supplied main 不能作为可信基线，重复/坏账本 fail-closed。
- 定向测试包含真实 Git worktree、路径重叠、脏树、Unicode/大小写风险、二进制、rebase、无 Git index/object 副作用。该投影不是远端 main 新鲜度证明，合并前仍需 Host 重查。

## B3：高耦合真实试验与性能声明

- 新增真实 Git worktree 双 Lane 补丁与单集成者收口测试：共享 API 的不同文件，以及同文件不同函数；B2 覆盖 main 前进与 replay。它们证明机械协调路径，不代表两位 LLM Agent 已完成受控真实 A/B。
- 新增 `benchmark_multiagent_convergence.py`：仅消费可追溯的 serial / plain_parallel / lfl_coordinated 三模式、三任务族、每格至少两次的真实审查/R9/CI/Token/缓存/墙钟回执；无样本返回 `EXPLORATORY`，不同模型/硬件/预算返回 `INCOMPARABLE`，任何门禁失败返回 `NO_GO`。**尚未采集完整真实 LLM Agent A/B 样本，不得声称效率提升 ≥15%。**

## 收口顺序

1. 只读独立 Reviewer 复核冻结 v1.9 与本实施候选，逐条核验旧 P1；P0/P1 未清零不得称设计 PASS。
2. 修复代码级真实问题，冻结新精确候选 SHA；定向/负测、Ruff、Pyright、A.5，独立 Reviewer PASS P0/P1=0。
3. 原版完整 R9 exit0 → 远端精确 SHA PR/CI → Host 合法签发/受保护 main 集成 → main push CI。
4. 受管发布授权与四服务 desired/live/PID/health 验收；M2-A/真实 A/B/升级签发未通过则原 Goal 保持 active/HOLD，不以文档完成代替生产完成。
