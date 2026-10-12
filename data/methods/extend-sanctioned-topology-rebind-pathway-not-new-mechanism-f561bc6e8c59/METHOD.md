---
method_id: extend-sanctioned-topology-rebind-pathway-not-new-mechanism-f561bc6e8c59
name: extend-sanctioned-topology-rebind-pathway-not-new-mechanism
description: 当缺陷根因已定位到 runtime 资产/路径解析点，且运行拓扑是“进程从发布快照（linked worktree）运行、但资产语义上是活资产（工作区新增应即时可见）”时，不要在注册层、加载器或发布机制上另起炉灶。判别依据是三个当时已知事实：解析模块 docstring 已声明的拓扑规则、同构 mutable 资产已走通并有命名 pin 测试的 common-root 重绑通路、对运行中进程核实的拓扑前提。三者齐备时，唯一可信修复是把目标资产并入同一既有解析分支（显式配置 > 拓扑重绑 > 默认），用判别性 pin 测试和 A/B 全量失败集逐位对比收口。本方法把“修在哪一层”的多层候选缩成一个解析分支改动。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:fe0e1465-7509-459e-8792-eaaf6d7269f5:1206:c2eecef9b5dff642e4c9
evidence_refs: learning:learn:e4da3c656c51
created_at: 2026-10-13T03:37:11.828917+08:00
updated_at: 2026-10-13T03:37:11.828917+08:00
---
## Trigger
缺陷根因已定位到某资产目录/路径的 runtime 解析点（如从发布快照运行的进程读不到工作区新增资产），需要决定修复放在哪一层（注册/加载器/发布机制/解析函数），且必须不破坏非该拓扑场景与显式配置的行为。

## Discriminator
进入修复设计时已存在的事实：① 解析模块 docstring 明文声明拓扑规则（“Tracked assets follow the exact code root. Linked Git worktrees share the primary repository state by default”）；② 同一 RuntimePaths 结构中同构 mutable 资产（data/experiences）已经走 common_root 重绑通路，并有命名 pin 测试（test_linked_worktree_without_data_dir_anchors_state_to_git_common_root）证明该通路是 sanctioned 机制；③ 已对运行中进程核实前提：发布目录 git-common-dir 指回主工作树 .git。三者共同把修复空间从“多层候选”缩成“解析函数内并入既有分支”。

## Short path
- 核实拓扑前提：对发布目录执行 git rev-parse --git-common-dir 并对照运行中进程列表，确认“快照运行”确为 linked worktree 且 common root 指向主工作树（未知量：解析侧修复是否真能生效）。
- 读既有解析函数与同构资产的分支及其 pin 测试，确认 sanctioned 通路的精确形态与优先级约定（未知量：既有通路长什么样、显式配置如何最优先）。
- 在解析函数同一分支并入目标资产：explicit env > topology rebind > default，非 linked 场景行为保持逐位不变（未知量：最小且不越权的改动点）。
- 新增判别性 pin 测试：仅 linked 场景重绑、显式配置仍最优先（未知量：改动是否精确生效且不误伤）。
- A/B 全量基线对比：无改动与含改动的 failed/passed 集合逐位一致，净增仅新测试（未知量：无回归）。达标即停止，不再扩测。

## Stop conditions
- 根因已在解析链（config 默认 → paths 解析 → 注入点）上验证为拓扑绑定问题后，停止在发布/注册/加载层继续找替代解释。
- 修复后定向测试通过，且 A/B 全量失败集合与基线逐位一致、净增仅新测试——停止验证，入库。
- 拓扑前提被证伪（发布目录并非 linked worktree / common root 不指回工作区）时，停止本方法，改查发布/复制时序层。

## Verification
- 新增 pin 测试断言三件事：仅 linked 场景发生重绑、显式 SKILLS_DIR/env 永远最优先、非 linked 场景解析结果与改动前完全一致。
- A/B 全量基线：对比无改动与含改动两次全量 run 的失败集合逐位相等（预存失败不归因于本次改动），净 delta 必须恰好等于新增测试。
- 独立审查回执确认：改动只落在解析函数目标分支，未改动其他 tracked 资产（docs/method_seed 等）的跟随语义，并如实记录生效边界（已运行进程需重启才生效）。

## Counterexamples
- 同构资产语义上必须跟随精确 code 快照（如 docs/method_seed 属 versioned tracked assets）——重绑到主工作树会破坏可复现性，不得因“拓扑相同”而套用。
- 不存在既有同构通路（独立部署、无 worktree、无 common root）——此时才需要新机制（watcher/发布侧变更），不要强行制造重绑分支。
- 缺陷实际在发布/复制时序（快照内容本身错误或缺失），而非解析时——解析侧重绑会掩盖上游问题，应修上游。
- 用户/运维已显式配置该目录——任何拓扑重绑都不得覆盖显式值，此场景应直接核实显式路径而非改动解析默认。
