---
method_id: premise-survival-preflight-before-conditional-branch-1d2ae7ddd94e
name: premise-survival-preflight-before-conditional-branch
description: 执行含条件分支的授权或计划时（'若确认 X 则允许执行 Y'），先对每个前提断言做一次只读机械 preflight：(1) 被引用符号/commit 在 HEAD 的存留（grep + git log）；(2) 生产实例状态回执暴露的 generation/git_head 与 HEAD 的 git diff。这两类只读证据直接裁决'已实现未生效'类断言，权威性高于任何历史叙述文档（旧审计、CHANGES、外部审查）。前提为假 ⇒ 整支取消（如 publish/restart），不执行零增量生产动作，并按实际生效状态重定义衍生指标（T0、计量口径）；前提成立 ⇒ 按授权进入分支。配置开关是独立轴：关闭≠未生效，必须与代码/部署轴分开记录，不得混入'待生效'清单。反模式：按历史文档复述状态直接开跑；前提核验前就执行 restart 类动作；把配置项为 0 误读为机制缺失。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ae8c5d92-6fe9-45af-bd9c-ef4912bb21e4:85:941f98381a82a429c3fc
evidence_refs: learning:learn:a1b1640003e7
created_at: 2026-10-07T23:18:38.522907+08:00
updated_at: 2026-10-07T23:18:38.522907+08:00
---
## Trigger
收到或执行一份含条件分支的授权/计划，条目前提是关于代码库或部署状态的断言（'某机制已实现未部署'、'某符号已删除'、'尚未 publish/restart'），且分支动作具有生产性或难回滚性（publish、restart、迁移、发布）；环境可提供只读核验手段：git 历史/diff、grep、服务 generation/git_head 回执。

## Discriminator
断言中每个实体都可机械核验且证据在动作前即可获得：引用的 commit/符号名可在 HEAD 做存留检查（grep 零命中或命中）；部署回执暴露运行 generation+git_head 并带 matches_desired/restart_required 标志；git diff <deployed>..HEAD 的文件清单就是'待生效改动'全集。三个只读证据合起来足以裁决断言真伪，无需读任何历史文档。

## Short path
- 从授权文本抽出前提断言清单（主体+状态+引用锚点），标注每条 gating 哪个分支动作——未知量：哪些断言决定哪些动作
- 一次只读批量核验：git log 确认引用 commit 在主线；grep 引用符号@HEAD；查服务回执取 generation/git_head；git diff <deployed>..HEAD——未知量：断言与当前事实是否一致
- 前提为假 → 取消整支，入档'假前提+证据'，衍生指标改挂实际生效 generation（如 T0=部署代启动时刻），计量口径按实际存在机制重写——未知量：分支去向与指标口径
- 前提成立 → 最小执行分支动作，T0 从实际生效代起算
- 配置开关状态单列记录为召回/行为决策，不并入'未生效'清单；汇报时逐条给出 断言→证据→裁决 表

## Stop conditions
- 每条前提断言均有裁决（成立/为假/不可机械判定）且对应分支去向已定
- generation+diff+grep 三类证据已覆盖全部断言后停止，不追加核验面
- 回执 matches_desired=true 且 diff 清单与断言对账完成 → 直接进入执行或入档，不重复复查

## Verification
- git diff <deployed>..HEAD 输出文件清单与'已实现未生效'断言集合完全对账（代码文件为零 ⇒ 无待生效改动）
- 被引用符号 grep --include='*.py' 零命中 ⇒ '已删除'断言成立；命中 ⇒ 断言部分不成立需改写
- 服务回执 matches_desired=true / restart_required=false 与'未部署'类断言直接矛盾 ⇒ 该前提为假，禁止进入其分支
- 产出指标只统计实际存在机制（如 pull-mode 调用/使用记录），不含已删除载体（如尾注计数）

## Counterexamples
- 前提是语义/设计判断（'该方案是否最优''缺口是否真实'）：grep/diff 无法裁决，应走评审或实验，不套用本方法
- 部署环境无 generation/git_head 回执或多实例状态分裂：机械 diff 不可得，须先建立权威状态源，本方法退化为普通核实
- 授权是无条件指令（无'若…则允许…'结构）：preflight 结果只能重排顺序与披露风险，不得用于取消已授权动作
- 断言指向未来或运行时行为（'重启后指标会上来'）：机械核验不可得，应转为假设+观察窗，而非判真伪
- 历史文档与机械证据一致且锚点抽查通过时，不展开整套 preflight，避免为已确认事实重复建流程
