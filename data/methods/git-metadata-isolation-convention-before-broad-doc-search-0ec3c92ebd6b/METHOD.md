---
method_id: git-metadata-isolation-convention-before-broad-doc-search-0ec3c92ebd6b
name: git-metadata-isolation-convention-before-broad-doc-search
description: 用户要求在存在进行中开发/测试的仓库建立'单独干净的分支环境'时，先用 git 自身元数据（toplevel、status、worktree list、既有分支命名样本）确认仓库已验证的隔离惯例并照搬执行；把文档 prior-art 搜索和文件名宽枚举推迟到隔离这一阻塞未知量解决之后；写入新文档前采样目标目录既有命名模式，提交前验证新环境零污染。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d4b773f7-7796-4ff1-a76a-310f94b7feff:69:269db424cec1f9b71fd7
evidence_refs: learning:learn:7f6812e85d8b
created_at: 2026-09-25T11:00:38.614453+00:00
updated_at: 2026-09-25T11:00:38.614453+00:00
---
## Trigger
用户要求在不干扰进行中开发/测试的前提下建立隔离分支环境写文档或改代码（或任何'不触碰现有 WIP'的并行写任务），且未指定具体隔离方案

## Discriminator
第一条 git 输出已同时暴露：仓库 toplevel、当前分支、未跟踪运行期产物、以及 .worktrees/<名字> 布局或既有分支命名模式（如 docs/<主题>-<日期>）——这组 git 元数据本身已把'用哪种隔离方式'从开放选项（新 clone/stash/自创目录）缩到照搬仓库已验证惯例

## Short path
- 一次 git 调用取 toplevel+status+worktree list+近期分支名样本：未知量=仓库已用哪种隔离惯例、基点取哪条分支
- 存在 .worktrees/<名字> 惯例 -> git worktree add .worktrees/<主题-日期> -b <类型>/<主题>-<日期>，基于主线得到零污染干净检出
- ls 目标目录既有文件名（SPEC*/DESIGN* 等）采样命名与文档头风格，再写新文件
- 新环境 git status 应只含预期新文件；抽查易错段（嵌套 fenced block）后提交
- 核对提交回执（commit sha、安全扫描），声明交付物后停止，不再补做宽枚举

## Stop conditions
- 隔离环境已建立且其 git status 只含预期新文件（主仓 WIP 零接触）
- 新文件命名与目标目录既有模式一致并已提交（含扫描回执通过）
- 用户已明确指定分支/目录/基点时，停止惯例发现直接执行

## Verification
- worktree 内 git status 仅显示预期新增文件，无主仓运行期未跟踪产物泄入
- git log -1 确认分支基于预期基点 commit（如 main@<sha>）
- 提交回执含安全扫描通过且工作区干净

## Counterexamples
- 仓库无任何 worktree/分支命名惯例且主工作区本就干净：直接 checkout -b 即可，强行造 worktree 是额外开销
- 用户已明确给出隔离方案（分支名/目录/基点）：照指令执行，无需发现
- 进行中改动与你将写的文件高度重叠：worktree 不能消除语义冲突，应先协调合并次序
- 纯只读检查任务：不需要任何隔离环境
