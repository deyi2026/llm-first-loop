---
method_id: runtime-self-binding-first-when-auditing-the-agent-host-project-868bbee383ff
name: runtime-self-binding-first-when-auditing-the-agent-host-project
description: 评估/审计当前运行时自身所属项目（用户常以昵称指代）的技术债时：cwd 往往只是任务工作区——先用运行时自绑定（code_root/git_common_root/data_dir）一次钉死主仓库，不做全盘同名前缀枚举；证据采集按『系统已承认的债（git 状态、健康 warnings、部署 live≠desired）优先于静态代码指标（lint/TODO/行数）』排序；用户附带的参考文章只当评估维度框架，不当被评对象；重命令收窄范围后再跑，防超时。
aliases: 评估自己正在跑的这套系统的技术债, agent 给自己家项目做体检从哪开始, 工作区里找不到源码，主仓库在哪, 别扫全盘找仓库，先问运行时, 技术债评估先看系统自己承认的债
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:8cdc10d0-aa2b-4b38-b050-e87862e63307:0:cbc19839f9bb3c3ef568
evidence_refs: learning:learn:5ded0a5b540f
created_at: 2026-10-27T22:10:26.920818+08:00
updated_at: 2026-10-27T22:10:26.920818+08:00
---
## Trigger
用户要求评估某项目的技术债或质量，而该项目正是当前运行时/工具链自身所属的宿主项目（按昵称呼叫）；cwd 探查显示的是任务工作区（补丁、临时目录、日志、无源码树），主仓库位置成为开放未知量。

## Discriminator
两件摩擦发生前已可见的事实：(1) cwd 的 ls 全是任务残渣（*.patch、.tmp-*、日志、STATUS 报告），无 src/pyproject——当前目录不是主仓库，且 home 下存在多个同前缀候选（工作区/隔离区/运维目录），按名字枚举无法裁决；(2) 本会话的记忆/文档检索回执全部是该项目自身的内部记录——说明运行时自状态通道（健康快照的 binding 字段）会直接给出权威 code_root/git_common_root，这是最窄、无歧义的下一跳。

## Short path
- 读用户附带的参考材料（如警示文章），只抽取评估维度（代码债/认知债/验证债），明确它是评分框架而非被评对象。
- cwd 探查确认非源码树后，把『主仓库在哪』当作唯一先决未知量：查询运行时自绑定一次钉死 code_root/git_common_root/data_dir，不做全盘目录枚举。
- 在主仓库先采『系统已承认的债』：git status（未提交/未合并分支/worktree 数）、健康快照 warnings（如知识库存未入库积压）、部署 live vs desired（只读快照）。
- 再补便宜的结构指标：行数 Top 文件、lint/TODO 计数、最近一次已登记测试基线（引用日期，不重跑全量）；重命令（du、全量测试）只在范围收窄后跑，避免超时。
- 文档证据优先按检索回执里已点名的权威文档直读，首次 miss 后不换措辞重搜。
- 每个维度一个量化事实即停，输出按 ROI 排序的偿债顺序，并标注数据日期与只读快照边界。

## Stop conditions
- 主仓库路径已由运行时绑定钉死并经 git 实测验证一致。
- 每个评估维度都有至少一个来自权威来源（运行时绑定/git 状态/已登记报告）的量化事实。
- 全程只读评估完成，未触发任何修复或部署变更。

## Verification
- git -C <code_root> 的 common-dir 与当前分支和运行时报告的 git_common_root 一致。
- 引用的测试/安全/部署数字均标注来源日期；登记报告不得当作当前 HEAD 的事实，需注明『未重跑』。
- 运行时绑定若存在 auto-rebind 过期风险，以 git 文件系统实测覆盖自报路径。

## Counterexamples
- 被评估项目不是当前运行时的宿主（用户问的是另一个仓库/组织）→ 自绑定通道无关，应直接向用户确认或按明确命名定位。
- cwd 本身就是主仓库（可见 src/、pyproject、.git）→ 跳过定位步骤，直接进入维度采集。
- 运行时自报路径与文件系统明显矛盾（如指向已删除的发布快照）→ 以 git 实测为准，不盲信自报绑定。
