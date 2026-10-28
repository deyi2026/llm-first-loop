---
method_id: live-config-carrier-authority-for-enablement-claims-8d4742a5d55e
name: live-config-carrier-authority-for-enablement-claims
description: 判断由环境变量/本地配置驱动的可选机制在当前部署是否实际启用或有无数据时，代码默认值与 git grep 是错误权威：.env 被 gitignore 则必然零命中，零命中只证明'无跟踪配置'，不证明'未启用'。正确路径：从配置加载代码读出键名，直读活配置载体（.env/部署环境/已被命中的 env inventory 报告），再用运行态事件正证据（EventStore 条数、session、时间窗）交叉验证后才写结论；文档中把'代码默认/活配置/运行态实测'三层分开并限定适用范围，防止用间接证据替代直接核查导致整轮返工。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:148:3c1ff54ce8c94aff5a6b
evidence_refs: learning:learn:4fd45c1276d6
created_at: 2026-10-15T00:11:20.297969+08:00
updated_at: 2026-10-15T00:11:20.297969+08:00
---
## Trigger
需要断言某个 env 驱动的可选机制（feature flag、advisor、采样/观测链路）在当前部署是否实际启用、是否已产生数据；手上已有代码默认值与 git 内 grep/搜索结果，正准备据此下'默认关闭/无样本'类结论或给方向性建议。

## Discriminator
配置加载代码本身已显示该开关来自环境变量（如 _mode("LFL_X", "off", {...})），即真值载体是运行环境/.env/部署配置而非 git 跟踪文件；gitignored 文件在 git grep 中必然零命中——零命中只证明无跟踪配置，不证明未启用。同一 grep 输出中的 env inventory 报告行往往已给出活值（本集 REPORT-20261014-env-inventory.md:82 已写明 shadow）。

## Short path
- 把未知量明确为'当前部署的实际 mode'，而不是代码默认值或仓库内声明。
- 从加载代码读出配置键名，直读活配置载体：.env / 部署环境 / 已被 grep 命中的 env inventory 报告。
- 用运行态正证据交叉验证：只读扫描 EventStore/日志中该机制特有事件（条数、session 数、连续时间窗）。
- 两层证据一致后才写入文档，并把'代码默认/活配置/运行态实测'三层分开表述、限定数值适用范围（本工作区 vs 其它部署）。

## Stop conditions
- 已取得活配置实际值，且运行态事件证据与其一致（启用且有数据）或双负（未启用且无事件）。
- 确认该开关不存在 env/本地 override 路径、仅 tracked 配置可设定——此时代码默认即权威，停止外查。

## Verification
- 复述结论时能同时给出三层证据及来源：config.py 默认行、.env 行号+文件 hash、事件计数+时间窗。
- 检查文稿与建议中不存在'git grep 零命中 ⇒ 未启用'式推理，也不基于未验证前提给出方向性动作（如'先开 shadow 采样'）。

## Counterexamples
- 设置仅由 tracked 配置文件决定、无 env override：repo 搜索+代码默认即足够，读 .env 是多余动作。
- 问题本身是'未设置时的回退行为/全新安装的默认'：代码默认就是权威答案，无需查活配置。
- 平台注入 env、本地无 .env：应以运行态事件日志为权威，读 .env 会误判为未启用。
- 机制刚部署、运行时间窗很短：运行态无事件不等于未启用，此时以活配置值为准。
