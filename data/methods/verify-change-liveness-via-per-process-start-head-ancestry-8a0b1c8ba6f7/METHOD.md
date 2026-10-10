---
method_id: verify-change-liveness-via-per-process-start-head-ancestry-8a0b1c8ba6f7
name: verify-change-liveness-via-per-process-start-head-ancestry
description: 已提交 ≠ 已生效。回答『并到 main 了吗/要重启吗』时，把『已在 main』与『运行进程加载的代码』当两个独立未知量。先定位仓库（用会话自身可查上下文，不猜绝对路径）；再列出该变更的全部提交（同一动因可能有散在不同分支的姊妹提交）；对 main 做祖先测试回答『已合并』；然后读运行时进程版本回执，按各服务启动时 git_head 逐个做同样的祖先测试回答『已生效』。分支：启动点缺提交→需重启；部署 checkout 本身也缺提交→先对齐 checkout 再重启（单纯重启无效）；运行时持久化的数据/配置项单独判定，不进进程测试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cbdfc9d0-6bd9-445c-a2af-0452afd6becb:424:9773fd795646b7ebf9e5
evidence_refs: learning:learn:387ecd752370
created_at: 2026-10-10T13:52:17.380129+08:00
updated_at: 2026-10-10T13:52:17.380129+08:00
---
## Trigger
用户询问某已提交代码变更『是否已并入 main / 是否生效 / 是否需要重启』，环境存在多个长驻服务且运行时回执暴露各服务启动时 git_head，而仓库位置与各进程代码新旧尚属未知。

## Discriminator
当时可见的判别事实有二：(1) 仓库位置应取自当前会话可零成本查询的上下文（pwd / git rev-parse --show-toplevel），记忆中的跨机器/跨用户绝对路径不是证据；(2) 『是否生效』的决定性检查既非『是否在 main』、也非运行时 code_current 自评（它只对照进程自身工作区，本集一个刚启动服务的启动点不含目标提交却显示 true），而是变更提交与各进程启动时 git_head 的 merge-base 祖先测试。

## Short path
- 未知：目标仓库在哪 → 在当前会话上下文直接跑 pwd / git rev-parse --show-toplevel 判定，不猜绝对路径（本集首次猜路径即 128 失败）
- 未知：哪些提交实现了该变更 → 按变更/EVO 编号 grep git log --all，列出全部相关提交含姊妹提交
- 未知：已并入 main？→ git merge-base --is-ancestor <提交> main；顺带记录哪些姊妹提交不在 main
- 未知：各运行服务是否包含变更？→ 读运行时进程版本回执取各服务启动时 git_head，逐服务做祖先测试
- 分支：启动点缺提交→需重启；部署 checkout 也缺提交→先对齐 checkout 到 main 再重启；持久化数据/配置项→单独判定无需重启
- 每个服务均有『含/不含该提交』的裁决后汇总作答并停止

## Stop conditions
- 每个运行中服务都已用祖先测试得出是否包含变更提交的结论
- 『是否并入 main』已由对 main 的祖先测试回答
- 仓库位置已由 rev-parse 确认且所有 git 操作都在其中执行

## Verification
- 含/不含只以 git merge-base --is-ancestor 的退出码为依据，不用提交信息措辞或回执定性词替代
- code_current / workspace dirty 标志只作漂移提示；任何『已包含变更 X』的结论必须经祖先测试独立验证
- 同一变更的姊妹提交逐一检查是否在 main 上并如实上报，防止后续引用错提交

## Counterexamples
- 变更是运行时持久化的数据/配置（如注册即持久化的 schedule）：不依赖进程代码版本，无需祖先测试或重启
- 无长驻服务、一次性在同 checkout 执行的场景：并入 main 后更新 checkout 即足够，逐进程测试是冗余
- 部署不是 git checkout（容器镜像/打包发布）：不存在启动时 git_head，应改比对镜像版本/构建信息，不强套祖先测试
- 会话上下文不含目标仓库（跨机/远程目标）：rev-parse 失败或返回无关仓库，此时应改从部署配置/回执获取位置，但同样不得凭记忆猜路径
