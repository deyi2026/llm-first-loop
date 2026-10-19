# GitHub 版本管理与正式发行（维护者指南）

> 官方公开仓：[`deyi2026/llm-first-loop`](https://github.com/deyi2026/llm-first-loop)；本地镜像 Git remote **`lfl`** 指向它，`origin` 指向旧 `llm-first-loop-legacy`，不得混用。源码和真实发布状态以 GitHub 远端 `main`、不可变 tag、Actions 与 Release API 为准。本指南公开维护步骤，不是自动获得的 Push/Release 授权。

## 版本与主线

- **版本单一真值**：`pyproject.toml` 的 `project.version`，格式 `MAJOR.MINOR.PATCH`。每次新发行同步 Web `SERVICE_VERSION`（`src/llm_loop/web/routes.py`）、`uv.lock` 中项目包版本、README/README.en 版本号及 CHANGELOG 顶部段；运行 `tests/unit/test_version_consistency.py`。旧测试用例中的旧版本样例是兼容性测试，不应全仓无差别替换。
- **受控集成**：从公开 `lfl/main` 的准确 HEAD 衍生最小候选，使用 PR 展示差分，先独立 GLM-5.3 代码审查通过、完整原版 R9 与安全扫描全部通过，才隔离提交和受审 Push。发布前确认 GitHub PR 真实 CI 状态。**禁止把比公开 `main` 超前许多提交的本地开发 `main` 直接推送**，防止带出未经审查的内容。
- **单向历史**：合并后检查 `lfl/main` 的精确 SHA 与 PR 合入结果及版本一致性；不用 `--force` 覆写公共 main/tag。Tag 只指向已经进入公开 main 且通过门禁的确定提交；既有 tag 绝不移动或重用。版本增量至少高于现有最高版本，不把 Draft 当作已发布稳定版。

## 从候选到公开 Release

**PR 架构审查规则**：所有 PR 都需要恰好一份本轮变更的 `docs/governance/submissions/*.json` 清单，内容覆盖公共基线到 PR HEAD 的所有路径（包括清单自身），涉及实际控制代码的组件填写 G1–G4；使用 `scripts/check_architecture_submission.py --base <base> --head <head>` 验证，再等待 GitHub A.5 Architecture Review 通过。不得禁用或绕过此门禁。

1. 检查 `git ls-remote lfl 'refs/heads/main' 'refs/tags/v*'`、`gh release list -R deyi2026/llm-first-loop` 与 PR/工作树无漂移。确认版本 `vX.Y.Z` 尚不存在，包/README/Web/锁文件/CHANGELOG 均一致。
2. 完成正式独立审核及完整原版 `bash scripts/ci_gate.sh`，对准确候选做安全扫描、发布/Push 审查；只合并指定 PR 的批准集合到 GitHub `main`，复核 Actions CI 全绿。仅在合入后打指向**公共 main 精确提交**的 `vX.Y.Z` tag，并用 `git push lfl vX.Y.Z` 发起 Release 工作流（不是 `origin`）。
3. `.github/workflows/release.yml` 是唯一自动 Release 写者：`v*` tag 推送 → 校验 tag 与 `pyproject.toml`、冻结环境 Ruff/Pyright/pytest 门禁 → 构建 Web UI、wheel、sdist → 真实安装/卸载验收 → 生成包含所有成品摘要的 `SHA256SUMS` → 生成同 tag **Draft Release**。Draft 不会出现在 `releases/latest`，也不是安装器的合法来源。
4. 逐项核对 GitHub Actions 的真实 `conclusion=success`、tag SHA、Draft 的 wheel (`llm_first_loop-X.Y.Z-py3-none-any.whl`)、sdist (`llm_first_loop-X.Y.Z.tar.gz`)、`install_linux.sh`、`uninstall_linux.sh`、`installation-smoke.json`、`linux-installer-smoke.json` 与 `SHA256SUMS`。逐文件验算 SHA256，且检查验收 JSON 的 Linux 平台/架构、包版本、升级回滚与卸载保留数据字段；摘要校验**不等于数字签名或供应链来源证明**。
5. 经独立文稿/发布审核和明确操作者授权后，把准确的 Draft 改为公开稳定 Release；再次以未登录消费者视角读取 `releases/latest`，核对 tag/assets/download URL 与摘要，再在干净 Linux 环境执行 `install_linux.sh`、`lfl --version`、`lfl check-install`、`lfl doctor`（缺少用户模型配置时 doctor 可合理报告需配置）和回滚/卸载保留数据测试。公开页面与实际 wheel 身份不一致即不宣称发行完成。

## 给普通用户的安装入口

```bash
# 保存脚本后运行；不直接将网络响应交给 shell
curl -fsSL https://raw.githubusercontent.com/deyi2026/llm-first-loop/main/scripts/install_linux.sh -o lfl-install.sh
bash lfl-install.sh
lfl doctor

# 指定已正式发布的稳定版本
bash lfl-install.sh --version 0.6.33
# 安全离线回滚（需有旧安装版本）
bash lfl-install.sh --rollback
```

应用采用用户级目录、无需 sudo；Linux `x86_64/glibc` 有原生 Ubuntu CI 验收，ARM64 需补独立 native CI 才宣称等价覆盖；Alpine/musl 不受支持。安装脚本和 wheel 版本以**真正已公开的 Release**为准；如 `v0.6.33` 尚是 Draft，则命令应安全拒绝而非静默拉取候选。详情见 [安装与升级](installation.md)。

## 回滚、历史与职责边界

- 应用回滚：`bash lfl-install.sh --rollback` 切回上个保留的已验证应用版本；卸载只移除安装器管理的应用文件，保留 `.env`、`data/`、methods、experiences。升级/回滚前先停止正在运行的对应应用进程，不触及项目受管服务生命周期。
- GitHub 源码回滚：不可改写已发布 tag/Release 的历史；发现缺陷先暂停引导新安装，再用新修复提交和新 patch 发行（或依据保护规则批准 `git revert`）。公开已发版的撤回与用户通知须单独说明。
- 维护流程只覆盖 GitHub 仓库/发行。**本地 `main` 集成、生产 Web/Feishu/Learning 部署、系统服务重启、macOS 签名/公证均是独立操作和授权**。GitHub Release 成功不等于以上操作已发生。
