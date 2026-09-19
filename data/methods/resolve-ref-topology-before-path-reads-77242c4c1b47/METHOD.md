---
method_id: resolve-ref-topology-before-path-reads-77242c4c1b47
name: resolve-ref-topology-before-path-reads
description: 核验一批锚定到精确 commit SHA 的声称（冻结点、artifact hash、分支状态）时，先用 git 拓扑命令确定该 commit 位于哪条分支、checkout 在哪个 worktree、是否为当前 HEAD 的祖先，再进入任何按路径的文件读取。判别依据：当前 HEAD 的 git log 不含目标 SHA，即可断定当前工作树的路径读取对该 claim 无信息量；git show --stat 只列本提交改动文件，freeze 类提交仅含 2 个文档属常态而非异常，不应误读为'实现缺失'。环境事实（如解释器是 python3 而非 python）用首次失败快速纠正即可。该方法把'在错误目录枚举路径 + 全量列出所有 worktree'的宽搜索，压缩为由拓扑事实直接导出的单跳定位。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e25ab65e-c8e1-413a-89e4-f5983daab0b3:27:0cea56a339ac7510bb47
evidence_refs: learning:learn:c86646b5fd6e
created_at: 2026-09-19T13:25:22.313061+00:00
updated_at: 2026-09-19T13:25:22.313061+00:00
---
## Trigger
审查/核验一批把结论钉在精确 commit SHA、分支名或工作区状态上的声称（如冻结点、hash 对账、'main 干净'），且当前目录 HEAD 与目标 SHA 的关系尚未确定

## Discriminator
git log 输出中不出现目标 SHA / 目标提交主题 → 该 commit 不是当前 HEAD 的祖先 → 当前工作树在对应路径上必然取不到该 commit 的文件，任何 ls/grep/pytest 在此目录都无信息量；同时 git show --stat 仅显示增量改动，纯文档 freeze 提交不等于实现缺失

## Short path
- git branch --contains <SHA> 或 git log --all --oneline --decorate 定位目标 commit 所在 ref；未知量：claim 锚点挂在哪条分支链上
- git worktree list（或按 ref 名过滤 .worktrees/）找到 checkout 该 ref 的 worktree；未知量：该 commit 是否有检出环境、是否干净停在冻结点
- 在正确的 worktree 内做针对性核验：status -sb、grep 具体声称的字段/import、SHA-256 比对、用环境实际存在的解释器（python3）重跑测试
- 对'进展可能比信里更靠前'的信号（存在新的 p11 类 worktree/分支）单独 status + 读其 scope/spec 文档
- 核对 main/根状态与远端，逐条 claim 对上回执即停，输出 claim→核验方式→结果 的对账表
- 把无回执的事项（CI gate 未跑、远端 push 失败）显式列为 pending 而非结论

## Stop conditions
- 信中每条可核验声称都有一条独立工具回执支撑（匹配或不匹配），没有强断言缺少证据
- 拓扑事实已使后续路径级读取可定向（不再需要枚举全目录或全部 worktree）

## Verification
- 最终对账表中每行 claim 都能指回具体命令回执（分支链、行号 grep、hash、pytest 输出）
- 重新抽查：对任一目标 SHA 先跑 branch --contains，确认选择的读取目录与包含它的 ref 一致

## Counterexamples
- 目标 commit 就是当前 HEAD（审计对象即当前基线）→ 拓扑解析是空操作，应直接读工作树并停止发现
- 声称涉及未提交/进行中的脏工作区（如另一 agent 的在途修改）→ commit 拓扑找不到它们，必须用 status/diff，本方法只解决'找对目录'不解决'审脏文件'
- 声称只锚定可能已移动的分支名而非 SHA → 必须先解析分支当前指向，不能沿用信中旧 SHA
