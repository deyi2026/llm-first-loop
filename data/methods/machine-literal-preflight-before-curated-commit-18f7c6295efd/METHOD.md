---
method_id: machine-literal-preflight-before-curated-commit-18f7c6295efd
name: machine-literal-preflight-before-curated-commit
description: 把本机开发的未跟踪文件裁剪后批量入库到有安全扫描/卫生策略的共享仓库前，先用环境中已暴露的机械事实做预检：pwd 回执给出的本机绝对 home 前缀、.gitignore 中对本地凭证与机器特定配置的排除注释。对候选文件 grep 绝对 home 路径/主机名/凭证模式，命中者改为从 artifact 自身位置推导路径并做语法校验，而非依赖扫描器拦截后返工或走豁免。同一原则覆盖 workdir 类参数：先探测真实目录，不猜规范路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:384:7e1d830474a68c7f6c7c
evidence_refs: learning:learn:ff52d2675eb4
created_at: 2026-09-24T09:19:32.172587+00:00
updated_at: 2026-09-24T09:19:32.172587+00:00
---
## Trigger
任务要求把本机开发的未跟踪文件（脚本/配置）经裁剪决定后提交进带 pre-commit 安全扫描或明确卫生策略的共享仓库；或工具调用需要 workdir/绝对路径参数而环境未显式声明时。

## Discriminator
提交前已可见的两条事实：(1) pwd 回执显示本机绝对 home 前缀（如 /Users/<user>/Project/...）；(2) .gitignore 已把本地凭证、机器特定配置、含密钥脚本列为拒绝类——即'机器绑定字面量'是该仓库已知会被拦截的类别。本地临时开发的 shell 脚本常硬编码此类路径。这两条当时已出现，足以把'直接 add 提交'缩成'先按已知前缀 grep 再提交'。

## Short path
- 先 pwd 探测真实工作目录与本机 home 前缀，后续所有 workdir 参数引用该回执，不猜 /workspace 等规范路径。
- git status --porcelain 把工作分成 tracked 审阅与 untracked 裁剪两组，避免混在一起处理。
- tracked 按逻辑单元审 diff；对删除项用 git show HEAD:<path> 验证继任记录存在（沿 provenance 而非宽搜索）；跑相关单元测试。
- untracked 入库前逐项过三关：体积与 .gitignore 策略、凭证模式、已知 home 前缀 grep；命中的脚本改为从自身位置推导 ROOT（dirname $0），并 bash -n 校验。
- 按逻辑单元分组提交，安全扫描应首次即通过。

## Stop conditions
- 所有候选通过字面量/策略扫描，提交被扫描器一次接受且未使用豁免通道。
- 纯数据/生成型产物且不含可执行路径字面量时，策略与体积检查通过即可停止预检。

## Verification
- 对每个已暂存候选执行 grep 本机 home 前缀（及 /home/）无命中，或命中仅为 shebang 等标准系统路径。
- 安全扫描在首次提交尝试即通过；路径改写后语法检查（如 bash -n）通过。
- workdir 类调用零参数错误：均引用探测回执。

## Counterexamples
- 单机个人仓库、无扫描器与卫生策略——预检只有成本没有收益，不应套用。
- vendored/第三方脚本中的契约性绝对路径（如系统 shebang）不应被改写。
- 提交的是生成型结果数据（评测 JSON 基线）：其中的路径字面量属数据内容而非可移植性缺陷，grep 修复无意义。
