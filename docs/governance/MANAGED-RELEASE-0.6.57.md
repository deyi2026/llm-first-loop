# 0.6.57 受管发行：候选证据与切换计划（Deepin 本机）

- 日期：2026-11-22
- 状态：候选已由官方 committed-build 入口产出并通过远端 CI；本机切换在本文落盘时尚未执行
- 上一发行基线：已安装 0.6.56 / desired generation 19
- 依据通道：`$HOME/.local/share/lfl/audit/MANAGED_RELEASE_GATE.md`（本机权威受管发行闸）

## 1. 发行身份（逐项实测）

| 项 | 值 |
| --- | --- |
| 上一发行基线 commit | `07fd45f0de4eb62d7f2094014af6d3e3bdb5b867`（0.6.56） |
| 本次候选源 commit | `080ec9083f9e292dd31045f6b5be3d285b1c5d9c`（origin/main，PR #93 合并提交） |
| 版本身份一致性 | pyproject / README / README.en / uv.lock / `SERVICE_VERSION` 同为 `0.6.57`（提交 `24036f6`） |
| wheel | `llm_first_loop-0.6.57-py3-none-any.whl`，sha256 `105f981515fe720b15f5146d9605cbae45a5ee1dc0971a4f9452a231e6ae1b3e` |
| sdist | `llm_first_loop-0.6.57.tar.gz`，sha256 `7b5052d6e901c8a2a7b812cb3ff2454f47d4c2a559dd4bb08d90cea2db90491c` |
| 构建入口 | `scripts/build_committed_distribution.py --ref 080ec9083f9e…`（`build_source=detached-clean-git-worktree`，`offline_build=true`） |
| 构建 provenance | `webui_source_sha256=e8c515fce9a541789da0804619b80f2fdd46986c54a88d670869a03c5971899c`（147 tracked files）、`tracked_python_modules=648` |
| 发行增量 | `07fd45f0..080ec90` = 96 files changed, 15369 insertions(+), 241 deletions(-) |

构建环境的两个客观缺口与处置：本机原先没有 Node/npm 与 `webui/node_modules`，
按仓库文档要求「复用本机已安装的 WebUI 依赖二进制」在隔离目录以官方
`npm ci --ignore-scripts` 装好固定依赖（Node v22.23.5，tarball SHA-256 已对
官方 SHASUMS256.txt 校验），再交给官方构建入口；`uv build` 需要 Python ≥ 3.13，
本机 3.13 解释器位于 `work/.uvpython/cpython-3.13-linux-x86_64-gnu`（与仓库
`.venv` 同一解释器 3.13.18），已置于 PATH。WebUI 源码指纹与既有 0.6.56 产物
一致（`e8c515fc…` / 147 files），即本次未改动 WebUI 源码。

## 2. 远端 CI 与受保护分支 required checks

权威集合以 `docs/governance/required-ci-checks.json` 为准，共 5 项：

| required check | event_scope | 结论 |
| --- | --- | --- |
| 门禁（pytest + ruff + pyright） | push_and_pr | success |
| 安全扫描（敏感/私密/错误文件拦截） | push_and_pr | success |
| managed-premerge-evidence | push_and_pr | success |
| privacy-gate | push_and_pr | success |
| A.5 架构提交审查（机械 presence/coverage） | pr_only | success（PR #93 上运行） |

- PR #93 head `4678fe6` 的 check-runs 共 10 项：上表 5 项 required 全 success，
  另有 `部署 env 泄漏门禁（D4）`、`Linux 用户级安装/卸载真实成品验收（x86_64）`、
  `Linux 用户级安装/卸载真实成品验收（aarch64）` success，`nightly 真实 LLM 冒烟 + 评测集`、
  `nightly 信号类测试 50 次稳定性` skipped。
- 合并提交 `080ec90` 的 check-runs 共 9 项：A.5 检查为 `pr_only`、不在 push 事件上运行，
  故该提交上是 4 项 push_and_pr required + env 泄漏门禁 + 2 项 Linux 安装验收 success，2 项 nightly skipped。
- run 记录：CI `45024908374` success；privacy-scan `45024908270` success。
- 说明：`部署 env 泄漏门禁（D4）` 与两项 Linux 安装验收是附加检查，**不属于** required status check 集合。

## 3. 独立审查

- PR #93 上行审查：Host `review_admission(kind=git_push)` 共 10 轮，PASS 出现在第 6/9/10 轮，
  其余 7 轮判定 REVISE；最终 PASS 为第 10 轮：`child=subagent_7cde5c9a6e83`，
  `candidate_sha256=ef0fb04e…`，reviewer=minimax-review/MiniMax-M3.1-Flash。
  REVISE 轮次涉及 9 条 P2（ports 契约、整体时限、失败路径尺寸、超时下限、截断回报、
  httpx 墙钟上限、README 版本段、候选发现时限等），另有 1 条被判为 P1 的意见经复核为误判
  （文件确有 `from __future__ import annotations`），已让该行进入可见的增量 diff 消除歧义。
  轮次序列与 finding 处置以 `docs/governance/receipts/push-080ec908-origin-main-20261122.json`
  的 `review_history` 字段与 `docs/TOOL-CONTRACT-ENV-20261121.md` 第 7–13 节为准。
- 该 PASS 所审 head `4678fe6` 与本候选源 `080ec90` **树完全一致**（`git diff 4678fe6 080ec90` 为空）。
- 视觉契约工作另有两次 Host `full_test` PASS：`child=subagent_c0621e1f8b57`、
  `child=subagent_f02d67f9b6a0`（reviewer=glm/glm-5.3）。

## 4. 本机切换前事实（发布前基线实测）

- hostname 取本机运行时 `hostname` 的值（主机身份不写入版本库）；desired generation 19 / version `0.6.56` / wheel `74a9e0f2…`。
- live：web pid 4159536、feishu pid 4159642、learning pid 1140303，三者 `release_version=0.6.56`、
  `matches_desired_generation=true`、`guard_code_drift=current`、`restart_required=false`。
- `admission_barriers=[]`；`restart_all_coverage.physical_batch=[web, feishu, learning]`。
- `wecom` 无 live manifest（`live_manifest_missing`），不在 `--target all` 物理执行面内，
  需单独验收；本次不把 wecom 报为已验收。
- 本会话自身占用 web 的 active run lock（`web=confirmed_busy`），故物理重启由 service_control 的
  `waiting_for_requester_exit` → `waiting_for_idle` 两段等待在会话结束后执行。

## 5. 切换序列（受管通道；禁止手改 `managed_service_deployment.json`）

1. stage：`scripts/install_linux.sh --candidate <wheel> --expected-sha256 105f9815… --no-start`
2. publish：`releases/LFL-0.6.56/venv/bin/python -m llm_loop.runtime.service_control publish-wheel
   --lfl-home ROOT --data-dir ROOT/data --expected-generation 19`（CAS → generation 20）
3. restart：`service_control restart --data-dir ROOT/data --target all`；accepted 不等于完成，
   须等 durable action `status=succeeded` 且 `verify_verdict=confirmed_ok`
4. 验收：`$HOME/.local/share/lfl/audit/verify_managed_release.py --expected-host <本机 hostname>
   --expected-version 0.6.57 --expected-generation 20 --expected-sha 105f9815… --receipt <audit 回执路径>`

## 6. 回滚与失败判据

- 上一 release `LFL-0.6.56` 完整保留（release_dir + wheel + `.installer-wheel.sha256`），
  指针 `.LFL-previous-version=0.6.56`；`scripts/install_linux.sh --rollback` 可离线回切。
- 失败判据（任一命中即不得宣称完成）：required check 缺失或为红；候选 SHA 与声明不符；
  publish CAS 失败（说明有别的发布者改了代次）；服务未收敛到 generation 20；
  Web health 的 version/wheel SHA 与 desired 不一致。

## 7. 证据更正记录

- 2026-11-22：首次独立审查（`child=subagent_9834c3f37b45`）判 REVISE，P0=0/P1=0/P2=2，两条 P2 均属实：
  (1) 本文件原述「10 轮中前 9 轮 REVISE」与 push 回执的「PASS×3（第 6/9/10 轮）」互相矛盾；
  (2) 本文件原把 `部署 env 泄漏门禁（D4）` 列入 required checks 并漏列 `A.5 架构提交审查`，
  与权威集合 `docs/governance/required-ci-checks.json`（A.5 为 pr_only）不符。
  处置：按回源结果统一为「10 轮、PASS 在第 6/9/10 轮、其余 7 轮 REVISE」，
  并按权威文件重列 required checks（5 项）与其在 PR head / 合并提交上的 check-run 构成；
  push 回执 `review_history` 字段同步更正计数（原写法 9+3 与 10 轮不能同时成立），结论与 child/candidate 未变。
