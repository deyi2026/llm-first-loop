# 代码审查回执：release-restart CI 修复（仅测试，3 文件未提交改动）

- 审查人（subagent id）：`RULE-AI-28-code-review-subagent/20261027-release-restart-ci-fix`（父会话未派发外部 id，此为自标识；审查者角色，未修改任何被审文件）
- 审查时间：2026-10-27
- 分支/HEAD：feat/release-restart-eff-main @ 04ff8664d440f9a2eef907b977b0515b51ce50db
- 审查类型：RULE-AI-28 代码闸（全量测试前置独立审查）
- **Verdict: PASS**（附 2 条 P2 建议项，均非阻塞）

## 被审产物指纹（已与父会话固化值逐一核对一致）

| 产物 | sha256 |
|---|---|
| `git diff`（全量，HEAD→工作区） | `1c44a3818369b01ff49703e1088066b7f19462f41d30fb132cd3ec9e28d1b26c` |
| tests/unit/test_linux_installer_scripts.py | `2c57dea47dfce313ad086bd0653db3bbd54213673498dc4d00aaf3468844aa5b` |
| tests/unit/test_release_workflow_recovery.py | `9a5162bb957481e2d96e649fd1c9006ddcc17f6cc8678afea3ab0ec3889538d0` |
| tests/unit/test_service_control_worker_lifecycle.py | `884ba52ccb58e3688b0aef890328807e29085637d411e880e35ceadaf581d317` |

numstat：12/2、1/0、52/0（合计 +65/-2）。改动确实只碰这 3 个测试文件，未动产品代码与 release.yml。

## 必核项结论

### A. 白名单一致性 — 一致（PASS）
`.github/workflows/release.yml` 全文仅一处 `files: |`（第 152 行），块内容 153–160 行恰 8 项：
whl、tar.gz、install_linux.sh、uninstall_linux.sh、installation-smoke.json、linux-installer-smoke.json、SHA256SUMS、release-artifacts-manifest.json。
- test_linux_installer_scripts.py:548-557 期望集合逐项相等（8/8）。
- test_release_workflow_recovery.py:69-78 经 `yaml.safe_load` 取 `release["with"]["files"].splitlines()` 精确集合相等（8/8）。

### B. 解析修正 — 范围修正，非强度削弱（PASS，附 P2-1）
- 旧写法误收实证：以旧逻辑解析当前 release.yml 收集到 18 行非空行（含 release.yml:161-170「正文状态块」步骤的 name/env/run/注释行，均非 dist/），旧 7 项断言必失败——这正是 HEAD CI 3 红的成因之一，修正方向正确。
- 新写法（538-546 行）锚点受 537 行 `assert "          files: |\n" in workflow` 保护（缩进漂移即红）；行内缩进由 strip 归一；**真实资产漏收不可能静默**：期望集为精确 8 项，少收任何一项集合不等即失败。`assert assets`（547 行）堵住空收集。
- 未达 P1 门槛（P1=真实资产静默少收，此场景不可能发生）。

### C. test_update_detaches_by_default — 唯一改动为新增 `--target web`（PASS）
`git show HEAD` 版与新版剔除注释后逐字 diff：唯一差异为新增 `"--target", "web"` 两行（169-172 行区域）。numstat 全文件 52/0 零删除。四条 detach 断言逐字保留且未弱化：rc==0、spawn==["act-x"]、inline==0、receipt["detached"] is True（测试文件 173/174/175/179 行）。

### D. 新增 NEEDS_TARGET 用例 — 断言真实有效，非恒真（PASS，附 P2-2）
- fixture（测试文件 66-112 行）：`calls` 仅被 monkeypatch 到真实调用路径的 `fake_spawn`/`fake_inline` 改写；真实 CLI 在 src/llm_loop/runtime/service_control.py:4491（detached）或 --wait 内联路径调用它们。若拒绝前发生 spawn/inline，断言必红 → `spawn == []`/`inline == 0` 是"未发生"断言而非恒真。
- 产品侧结构（service_control.py:4315-4345）：`derive_restart_target` 失败 → stderr 末行 JSON → `return 2`，位于 build_deployment(4340+)/accept_restart(4440)/spawn(4491) 之前。
- 六项断言均为实质断言且实跑通过：rc==2、error=="NEEDS_TARGET"、basename=="repo"、targets==["web","feishu","learning","all"]（与 :111 `_ACTION_TARGETS` 元组顺序逐一相符）、example 含 `--target`、detail 含「未产生任何 publish/CAS 写入」。

### E. 回归面 — 未发现连带变红风险（PASS）
- `release-artifacts-manifest` 在 tests/ 下仅被本批 2 个被审文件引用；`files: |` 解析仅 test_linux_installer_scripts.py:537-538 一处。
- release.yml 另被 test_version_consistency.py、test_release_workflow_contract.py 引用；CLI `update` 另涉 test_svc_deploy_cli_update.py、test_service_control_argument_contract.py、test_webui_source_provenance.py、test_lifecycle_update_single_action.py、test_svc_deploy_next_step.py——以上 7 文件复跑全绿（109 passed）。
- 本批不改产品代码/release.yml；被审 3 文件夹具均为文件内局部，无共享夹具外溢。

### F. 「为过测试而放宽」迹象 — 未发现（PASS）
- 唯二删除行（linux 文件旧 538 行收集表达式）语义被等价保留并加强：新增非空守卫 + 白名单由 7 项扩为 8 项；集合精确相等（==）判定全部保留，无 in/any/len>0 弱化。
- 无新增 skip/xfail：linux 文件 2 个 skip 为 HEAD 既有 libc 条件跳过（`git show HEAD` 计 2 处 skipif，未在 diff 触碰）。
- 新用例只增断言；mock 仅限 worker 边界（与相邻既有用例同款 fixture 模式），CLI 解析/目标推导/错误回执均走真实代码。

## P0/P1/P2 清单

- **P0：无**
- **P1：无**
- **P2-1**：test_linux_installer_scripts.py:541-546 —— break-at-first-non-dist 解析存在理论盲区：若未来在 files 块**内部**插入非 dist/ 行（注释/空行）且在其**之后**追加未加白名单的 dist/ 资产，break 点之后的垃圾资产不会被收集，白名单保护对该复合场景失效（旧全量收集写法反而能抓到）。当前块内无任何非 dist 行，触发需复合未来编辑且块内注释行本身显眼，故 P2。建议改缩进界定块或 YAML 解析（recovery 文件 :69 已示范）。
- **P2-2**：test_service_control_worker_lifecycle.py:84-90 —— FakeStore 的 `compare_and_swap`/`accept_restart` 不记录调用，「零 publish/CAS 写入」由 rc/payload 断言+产品结构间接保证而非直接观测；若未来重构把 accept_restart 挪到推导检查之前，本用例可能仍绿。建议 fake 增记 CAS/accept 调用次数并纳入零副作用断言。

## 采纳/不采纳建议

- **采纳（非阻塞）**：P2-1——linux 白名单断言改用 `yaml.safe_load` 解析或缩进界定块，对齐 test_release_workflow_recovery.py:69 做法，可顺带消除盲区。
- **采纳（非阻塞）**：P2-2——`fake_store_cls` 记录 `accept_restart`/`compare_and_swap` 调用，零副作用断言扩为 spawn/inline/CAS/accept 四项。
- **不采纳**：恢复旧「files 块之后全部行」收集写法（会重新误收 release.yml:161-170 步骤，CI 复红）。
- **不采纳**：为本批另加「files 块内禁注释」类补丁断言（若采纳 YAML 解析则自然消解）。

## 复跑命令与真实输出摘要（worktree 自带 .venv）

1. `.venv/bin/python -m pytest tests/unit/test_linux_installer_scripts.py tests/unit/test_release_workflow_recovery.py tests/unit/test_service_control_worker_lifecycle.py -v`
   → **28 passed, 2 skipped in 7.13s**。三个原失败用例与新增用例均真实 PASSED（非 skip）：
   - test_github_release_checksums_have_bare_asset_names_consumable_by_installer PASSED
   - test_recovery_replaces_only_pinned_smoke_harness_not_release_source PASSED
   - test_update_detaches_by_default PASSED
   - test_update_without_target_rejects_needs_target_zero_side_effect PASSED
   （2 skipped 为既有 musl/libc 条件跳过，与本批无关）
2. 回归面：`.venv/bin/python -m pytest tests/unit/test_version_consistency.py tests/unit/test_release_workflow_contract.py tests/unit/test_svc_deploy_cli_update.py tests/unit/test_service_control_argument_contract.py tests/unit/test_webui_source_provenance.py tests/unit/test_lifecycle_update_single_action.py tests/unit/test_svc_deploy_next_step.py -q`
   → **109 passed in 7.98s**
3. 辅助验证（只读 python 单例）：旧解析逻辑对当前 release.yml 收集 18 行非空行（含 161-170 步骤内容），旧 7 项断言必失败；新逻辑恰收集 8 项，与 release.yml:153-160 逐项相等。

## 覆盖范围声明

- 已覆盖：全量 `git diff` 逐行审读；A-F 六项必核全部执行并给证据行号；被审 3 文件全量复跑；7 个回归面测试文件复跑；产品代码 NEEDS_TARGET 路径（service_control.py:4315-4345, 4440, 4491, :111）与 fixture 实现核读；release.yml files 块（152-160）及其后步骤（161-170）核读；`_ACTION_TARGETS` 顺序核对。
- 未覆盖/限制：未跑全仓 11582 用例（按委派仅要求相关用例+回归面；全量由父会话门禁执行）；未实测 GitHub Actions 远端行为；evidence 截断段已通过直接读文件补全；本环境无 search_records 工具，委派中的记录库方法论检索未能执行（不影响结论）。
- 审查者零改动声明：除本回执文件外未写入任何文件；三个被审文件 sha256 与父会话固化值一致即证未动。
