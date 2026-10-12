---
method_id: ground-git-target-coordinates-before-location-sensitive-git-ops-aa0ebfc35d75
name: ground-git-target-coordinates-before-location-sensitive-git-ops
description: 在多分支/多 remote/多 worktree 仓库中，默认名只是未验证假设：读待改文件前假设当前 checkout 即目标分支、建 worktree 时假设系统 tmp 可用、push 时假设 origin 是权威 remote。首个 `git status --short --branch` 回执其实已同时给出三个坐标：当前分支与 upstream remote 名、既有 worktree 约定目录、checkout 是否为目标 baseline。先解析这些命名事实再选目标，可避免错 baseline 读取、scope 外 worktree 返工、误推 legacy remote 三类绕路；push 回执混杂时不推断，用 ls-remote 单点重验。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:855926d8-3b7a-4a6d-9c5e-34631b59df2b:777:f5b0aebaf75976f643fa
evidence_refs: learning:learn:47ccb29f49c7
created_at: 2026-09-19T11:02:09.325066+00:00
updated_at: 2026-09-19T11:02:09.325066+00:00
---
## Trigger
多分支/多 remote/多 worktree 仓库中，即将执行位置敏感 git 操作（读取待修改文件、新建 worktree、push 到某 remote），或收到混杂 push 回执（传输错误 + up-to-date + exit 0）时

## Discriminator
首个 `git status --short --branch` 回执在动作前已存在且包含三个判别坐标：(1) `## <当前分支>...<upstream-remote>/<分支>` 表明当前 checkout 不是任务目标分支、且权威 remote 名不是默认 origin；(2) untracked 列表含仓库内既有 worktree 约定目录（如 .worktrees/，在编辑工具 workspace 范围内）；(3) 目标分支名来自任务上下文。任何与这三个命名事实冲突的目标选择，在当时即可判错，无需等失败回执

## Short path
- 起点先取 `git status --short --branch` + `git remote -v`（必要时 `git worktree list`），从回执解析三个坐标：当前 checkout 分支、权威 remote 名、worktree/scope 约定
- 当前 checkout ≠ 目标分支时：先查 worktree list 定位既有检出；无则在仓库内约定目录（须在编辑工具 workspace 范围内）新建 worktree，得到正确 baseline
- 在正确 baseline 上先用门禁同一 linter 精确复现错误（行号+规则一致），再取 snapshot 做最小修复
- 本地验证（linter + lint + 目标子集测试），git status/diff --stat 确认变更范围后提交
- push 到已解析的 remote 名，随后用独立干净的 `git ls-remote <remote> refs/heads/<branch>` 验证远端 ref 与本地 SHA 精确一致
- 轮询新 SHA 的 check-runs 至终态（短间隔重查，不用超过工具时限的长 sleep），必需检查全绿即停

## Stop conditions
- 远端 ref 与本地提交 SHA 精确一致，且新 SHA 所有必需检查终态为 success
- 本地在目标 baseline 无法复现门禁错误 → 停止改码，先核对 CI 实际使用的 commit/base SHA
- push 回执混杂或与远端重验结果矛盾且无法解释 → 停止重复推送，把 remote 身份/凭证当作待定事实处理

## Verification
- 读文件前确认其路径属于目标分支的 checkout/worktree（分支名与 worktree list 对得上）
- worktree 路径以一次 read_file snapshot 成功证明在 scope 内，再进入编辑
- push 后以 ls-remote 返回的 ref+SHA 为准，不依赖混合回执文本下结论
- 修复前 linter 在同一行同一规则报错、修复后 0 error，形成前后对照证明改对了对象

## Counterexamples
- 单 remote 干净 clone 且已检出目标分支：直接编辑-验证-push，坐标解析是纯开销
- 只读分析当前 checkout、无分支错配：无需 worktree/remote 核对
- CI 报错来自 merge commit 而非分支 HEAD：本地行号不匹配是预期现象，不构成 baseline 错配信号
- push 失败为认证/权限类（403）：问题在凭证流而非 remote 身份，核 remote -v 无益
