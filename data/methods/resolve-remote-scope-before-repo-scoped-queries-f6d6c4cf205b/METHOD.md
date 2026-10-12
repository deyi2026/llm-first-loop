---
method_id: resolve-remote-scope-before-repo-scoped-queries-f6d6c4cf205b
name: resolve-remote-scope-before-repo-scoped-queries
description: 在多 remote checkout（本地镜像 + 上游）中核验 PR checks / workflow runs / release 等仓库作用域远端对象时，这些对象归属拥有该工作流的 remote；归属 remote 通常已被先前可见痕迹点名（event_stream 里的 git 命令全部对照 `lfl/main`）。正确路径是先 `git remote get-url <remote>` 解析 owner/repo，再以显式仓库作用域（gh -R owner/repo）做一次只读查询。裸 gh 命令默认按当前目录仓库解析 PR 号，镜像仓库没有 PR #67，GraphQL 失败在调用前即可预判——失败回执、补搜索、再取 remote 的三步可压缩为一步。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:40eeca85-e561-4f26-9faf-efda5823cb4b:733:483258de1e8d8c2a1156
evidence_refs: learning:learn:53ef830937cf
created_at: 2026-10-11T01:54:04.608150+08:00
updated_at: 2026-10-11T01:54:04.608150+08:00
---
## Trigger
需要核验 PR checks / CI runs / tag / release 等仓库作用域远端对象，当前 checkout 存在多个 remote（镜像+上游），且先前命令回执或 event_stream 已点名拥有该工作流的 remote 名称。

## Discriminator
调用失败命令前已可见：本 session 发布链的全部 git 操作都对照上游 remote（`git diff lfl/main...8a56bff20`、`git merge-base --is-ancestor main lfl/main`、`git checkout main && git merge --ff-`），说明 PR/CI 工作流在 remote `lfl`；而 gh 裸命令按当前仓库作用域解析 PR 号——镜像 origin 下不存在 PR #67，失败可预判。

## Short path
- 从已可见的命令回执/event_stream 中确认拥有目标工作流的 remote 名称（无需新调用）
- git remote get-url <remote> 解析 owner/repo（一次只读调用）
- 以显式仓库作用域批量发出只读查询：gh pr checks 67 -R owner/repo + 最近 workflow runs
- 交叉核实 tag（git ls-remote <remote> refs/tags/...）与 release 属于同一上游仓库
- 所需事实全部由归属 remote 的一手回执确认后停止；mutation（restart 等）保持等待显式授权

## Stop conditions
- checks、合并后 CI、tag、release 等所需事实已由归属 remote 的回执确认，不再追加确认性查询
- 当前已持有来自归属仓库的等价回执，可直接引用，无需再查
- 涉及 mutation 时：授权链内无明确许可即不执行，仅汇报运行态与待授权项

## Verification
- 回执中 repo=owner/repo 必须与 git remote get-url 解析结果一致；不一致即作用域错误，中止该查询
- 最终结论表述为带时间戳的归属远端快照，而非本地缓存或镜像侧状态

## Counterexamples
- 单 remote checkout 且 origin 本身托管 PR：裸 gh 命令作用域正确，强行 -R 到其他 remote 反而查错仓库
- remote 名不能直接映射 GitHub owner/repo（SSH alias、非 GitHub remote）：必须先解析验证 slug，不能盲传 URL
- 对象 ID 已被先前回执证明属于当前 origin（如镜像侧自产的 PR/issue）：默认作用域即正确，无需换 remote
