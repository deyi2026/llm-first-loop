---
method_id: deploy-mismatch-resolve-commit-containment-before-host-or-record-searche-a2e219155c2a
name: deploy-mismatch-resolve-commit-containment-before-host-or-record-searches
description: 发布/重启后的行为探针返回与部署主张相反的旧签名（如材料体积精确等于预写旧值），且变更 commit 哈希与已部署快照 commit 哈希都已在手时，第一未知量不是『谁在服务这个行为』或『机制怎么实现』，而是『变更是否包含在已部署工件中』：用一条 git 包含性判定（merge-base --is-ancestor / branch --contains / 快照内 grep 新代码标志）直接裁决。不包含 → 定位提交所在分支 → 核对拓扑 → merge --no-ff → 聚焦单测 → 清 tracked 树 → publish → restart → 复探针收口。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4262a65a-bd51-4405-bed5-57af83e2e1ab:1794:9ef72484e508cb3f2816
evidence_refs: learning:learn:f0b30f2adc83
created_at: 2026-10-22T19:51:31.380912+08:00
updated_at: 2026-10-22T19:51:31.380912+08:00
---
## Trigger
部署/重启后的行为探针返回旧代码签名（与任务书/状态锚预写的旧特征值精确吻合），而上一轮记录声称该变更已部署；同时变更提交 id（任务状态已写明）与部署工件身份（.releases 快照哈希 / 进程 exe 路径 / venv editable 指向）都已直接可观察。

## Discriminator
两个具体 git 身份已在手：变更提交 id + 部署快照 commit。二者的包含关系可由一条命令机械判定且结论二值，不需要先弄清哪个进程托管该行为，也不需要理解机制实现；探针拒绝理由中的精确旧特征值（如 material=210866B）同时排除瞬态错误解释。当时已知事实：状态锚写明机制提交 7ce5cd99a，ps/.releases 显示部署快照为 5e05ab222——一条 merge-base 即可裁决，实际却先做了机制定义的记录检索和『工具宿主另有进程』假设。

## Short path
- 复探针一次确认旧签名稳定（拒绝理由含预写旧特征值，非瞬态、非探针自身用错参数）
- 读部署工件身份：ps 进程命令行+启动时间、.releases 最新快照哈希、venv editable 指向
- 一条包含性判定：git merge-base --is-ancestor <变更commit> <快照commit>（或 branch --contains；非 git 工件则在快照内 grep 新代码标志串）
- 不包含 → 根因=发布时源分支未并入：branch --contains 定位提交所在分支，main..分支 核对拓扑（单提交、可干净并入）
- merge --no-ff 并入 → 该模块聚焦单测全绿
- publish 前清 tracked 脏树：运行时账本工件按仓库既有惯例提交 chore（被跟踪却被 ignore 的文件用 add -f）→ publish → restart
- 换进程后复探针：签名从旧值变为新值（材料收窄/accepted=true）即收口；仅当包含性为真才转向宿主/环境绑定假设

## Stop conditions
- 复探针返回预期新签名（材料显著收窄或 accepted=true）
- 包含性判定为真（变更确在快照内）→ 本路径证伪，转查进程宿主/环境绑定
- 分支拓扑不可干净并入 → 先解决冲突，不强行 publish

## Verification
- merge-base --is-ancestor 退出码与结论一致，且对部署快照内容 grep 新代码标志串得到同一结论
- 重新发布后同一探针的签名从旧值变为新值
- 并入后模块聚焦单测全绿（本例 125 passed）

## Counterexamples
- 探针失败源于自身命令用错文件名/参数或瞬态错误，拒绝理由不含旧代码特征签名 → 先修正探针并复跑，不做包含性诊断
- 变更是配置/开关驱动、无 commit 哈希可查 → 改走『加载机制→开关→行为产物』链端点验证，不做 git 祖先判定
- 部署工件非 git 派生（无快照哈希）→ 只能对部署文件内容 grep 判包含，merge-base 无意义
- 行为确实由另一宿主进程服务且其工件身份未知 → 先确定该宿主的工件身份，再同样先做包含性判定，而非先做记录宽检索
