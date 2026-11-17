# GitHub 版本管理与正式发行（维护者指南）

> 官方公开仓：[`deyi2026/llm-first-loop`](https://github.com/deyi2026/llm-first-loop)。**remote 映射以 `git remote -v` 实测为准**：`origin` = 该正式仓（fetch+push 均指向它）、`gitee` = 镜像、`legacy` = 归档仓且 pushurl 为 `no-push://`（推送禁用），**无 `lfl`**。源码和真实发布状态以 GitHub 远端 `main`、不可变 tag、Actions 与 Release API 为准。本指南公开维护步骤，不是自动获得的 Push/Release 授权。

**发行状态快照（2026-11-16）**：GitHub [最新正式 Release](https://github.com/deyi2026/llm-first-loop/releases/latest) 为 `v0.6.50`；`v0.6.54` 已有不可变 tag、成功的 [Release 构建工作流](https://github.com/deyi2026/llm-first-loop/actions/runs/43731490249) 与 Draft，Linux x86_64/aarch64 资产状态为 ready，但 `macos_arm64=pending`，缺少 `LFL-0.6.54-macos-arm64*.pkg`，因此不能宣称正式发布。下一步应完成签名、公证和 Gatekeeper 验收，上传精确 tag 的 macOS 资产，重生成并验证 `release-artifacts-manifest.json`，再执行 `Finalize Release`；绝不可通过把 Draft 当稳定版或删去必需平台来绕过门禁。此段是带日期的核验记录，实时状态以 GitHub Release API 为准。

## 版本与主线

- **版本单一真值**：`pyproject.toml` 的 `project.version`，格式 `MAJOR.MINOR.PATCH`。每次新发行同步 Web `SERVICE_VERSION`（`src/llm_loop/web/routes.py`）、`uv.lock` 中项目包版本、README/README.en 版本号及 CHANGELOG 顶部段；运行 `tests/unit/test_version_consistency.py`。旧测试用例中的旧版本样例是兼容性测试，不应全仓无差别替换。
- **受控集成**：从公开 `origin/main` 的准确 HEAD 衍生最小候选，使用 PR 展示差分，先独立 GLM-5.3 代码审查通过、完整原版 R9 与安全扫描全部通过，才隔离提交和受审 Push。发布前确认 GitHub PR 真实 CI 状态。**禁止把比公开 `main` 超前许多提交的本地开发 `main` 直接推送**，防止带出未经审查的内容。
- **单向历史**：合并后检查 `origin/main` 的精确 SHA 与 PR 合入结果及版本一致性；不用 `--force` 覆写公共 main/tag。Tag 只指向已经进入公开 main 且通过门禁的确定提交；既有 tag 绝不移动或重用。版本增量至少高于现有最高版本，不把 Draft 当作已发布稳定版。

## 从候选到公开 Release

**PR 架构审查规则**：所有 PR 都需要恰好一份本轮变更的 `docs/governance/submissions/*.json` 清单，内容覆盖公共基线到 PR HEAD 的所有路径（包括清单自身），涉及实际控制代码的组件填写 G1–G4；使用 `scripts/check_architecture_submission.py --base <base> --head <head>` 验证，再等待 GitHub A.5 Architecture Review 通过。不得禁用或绕过此门禁。

1. 检查 `git ls-remote origin 'refs/heads/main' 'refs/tags/v*'`、`gh release list -R deyi2026/llm-first-loop` 与 PR/工作树无漂移。首次创建时确认版本 `vX.Y.Z` 尚不存在；若 tag/Draft 已存在，应按精确 tag 恢复而非重建或移动 tag。包/README/Web/锁文件/CHANGELOG 的**源码版本**须一致，并单独核对 GitHub 最新**正式 Release**。
2. 完成正式独立审核及完整原版 `bash scripts/ci_gate.sh`，对准确候选做安全扫描、发布/Push 审查；只合并指定 PR 的批准集合到 GitHub `main`，复核 Actions CI 全绿。仅在合入后打指向**公共 main 精确提交**的 `vX.Y.Z` tag，并用 `git push origin vX.Y.Z` 发起 Release 工作流。
3. `.github/workflows/release.yml` 是 Draft Release 的受管创建入口：`v*` tag 推送 → 校验 tag 与 `pyproject.toml`、冻结环境 Ruff/Pyright/pytest 门禁 → 构建 Web UI、wheel、sdist → 真实安装/卸载验收 → 生成 `SHA256SUMS` 与 `release-artifacts-manifest.json` → 创建同 tag **Draft Release**。Draft 不会出现在 `releases/latest`，也不是安装器的合法来源。
4. 逐项核对 GitHub Actions 的真实 `conclusion=success`、tag SHA、Draft 的 wheel (`llm_first_loop-X.Y.Z-py3-none-any.whl`)、sdist (`llm_first_loop-X.Y.Z.tar.gz`)、`install_linux.sh`、`uninstall_linux.sh`、`installation-smoke.json`、`linux-installer-smoke.json`、`SHA256SUMS`、`release-artifacts-manifest.json` 以及签名、公证并完成 Gatekeeper 验收的 macOS arm64 `.pkg`。逐文件验算 SHA256，检查 manifest 的三个必需平台均为 ready，并检查验收 JSON 的版本、架构、升级回滚和数据保留字段；摘要校验**不等于数字签名或供应链来源证明**。
5. 经独立发布审核和明确操作者授权后，在签名机上传 macOS `.pkg`，使用 `scripts/release_finalize.py manifest --tag vX.Y.Z --repo deyi2026/llm-first-loop` 按真实资产更新 manifest，再通过 `.github/workflows/finalize-release.yml` 的 `workflow_dispatch(tag)` 运行机械转正；**不得手动点 Publish 或放宽平台判据**。只有全部平台 ready、manifest 中的 SHA256/size 与远端逐资产实测一致，才会转为正式 Release。然后以未登录消费者视角读取 `releases/latest`，核对 tag/assets/download URL 与摘要，在干净 Linux 环境执行 `install_linux.sh`、`lfl --version`、`lfl check-install`、`lfl doctor` 及回滚/卸载保留数据测试。公开页面与实际 wheel 身份不一致即不宣称发行完成。

## 给普通用户的安装入口

```bash
# 保存脚本后运行；不直接将网络响应交给 shell
curl -fsSL https://raw.githubusercontent.com/deyi2026/llm-first-loop/main/scripts/install_linux.sh -o lfl-install.sh
bash lfl-install.sh
lfl doctor

# 指定已正式发布的稳定版本
bash lfl-install.sh --version 0.6.50
# 安全离线回滚（需有旧安装版本）
bash lfl-install.sh --rollback
```

应用采用用户级目录、无需 sudo；Linux `x86_64/glibc` 有原生 Ubuntu CI 验收，ARM64 需补独立 native CI 才宣称等价覆盖；Alpine/musl 不受支持。安装脚本和 wheel 版本以**真正已公开的 Release**为准；如指定的版本仍是 Draft（例如本次核验时的 `v0.6.54`），则命令应安全拒绝而非静默拉取候选。详情见 [安装与升级](installation.md)。

## 回滚、历史与职责边界

- 应用回滚：`bash lfl-install.sh --rollback` 切回上个保留的已验证应用版本；卸载只移除安装器管理的应用文件，保留 `.env`、`data/`、methods、experiences。升级/回滚前先停止正在运行的对应应用进程，不触及项目受管服务生命周期。
- GitHub 源码回滚：不可改写已发布 tag/Release 的历史；发现缺陷先暂停引导新安装，再用新修复提交和新 patch 发行（或依据保护规则批准 `git revert`）。公开已发版的撤回与用户通知须单独说明。
- 维护流程只覆盖 GitHub 仓库/发行。**本地 `main` 集成、生产 Web/Feishu/Learning 部署、系统服务重启、macOS 签名/公证均是独立操作和授权**。GitHub Release 成功不等于以上操作已发生。
