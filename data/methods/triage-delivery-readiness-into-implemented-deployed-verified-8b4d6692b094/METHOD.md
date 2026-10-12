---
method_id: triage-delivery-readiness-into-implemented-deployed-verified-8b4d6692b094
name: triage-delivery-readiness-into-implemented-deployed-verified
description: 对『X 是否已具备/可以使用/上线』类交付状态问题，不要用关键词文档枚举开局，也不要用单一证据回答：拆成三个各有权威记录的未知量——①实现状态：git log 提交信息索引出特性分支与设计文档 ID，再读文档的阶段/出口节；②部署状态：从服务状态回执取运行 commit/generation，用 branch --contains / rev-list 判定运行版本是否包含特性提交、落后 HEAD 多少；③验证形态：fixture 单测还是真实包冒烟。三层各挂一条已核对记录后成稿。本集两次宽搜未命中（关键词 docs、加内容过滤的 search_files）都输给了提交信息里的精确 provenance；且最终答案的价值在于拒绝用『单测全绿』推出『可使用』。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e80a8cde-8a96-4b11-ad03-3f16341a32f5:1749:bb44887b0cb9a961e8a2
evidence_refs: learning:learn:e52cc35d5383
created_at: 2026-10-09T13:05:14.726945+08:00
updated_at: 2026-10-09T13:05:14.726945+08:00
---
## Trigger
用户询问某功能是否『已经具备/可以使用/上线』，工作区为 git 仓库，且存在可查询的运行时状态（服务 generation/运行 commit）或带阶段表的设计文档。

## Discriminator
git log 回执的提交信息已显式索引特性工作：分支名（feat/p1a-standard-packages）+ 阶段（P0/P1-A/B/C）+ 设计文档字面 ID（DESIGN-20261009-plugin-ecosystem-integration）；服务状态回执暴露各 target 的运行 generation/commit。这两个当时可见事实把『全库文档可能含答案』缩成三条子问题；其中运行 commit 是否为 HEAD 祖先、落后几个提交，直接裁决部署层。

## Short path
- git log --oneline -N && git status -sb：从提交信息定位特性分支、已完成阶段与设计文档 ID（解决『实现了什么、到哪阶段』）
- 用提交信息里的字面文档 ID 直接 grep/打开设计文档阶段/出口节（§11）：确认阶段口径（P0≠MVP，P1=MVP，P2 明确未做）
- 读服务状态回执：取目标服务的运行 commit/generation（解决『跑的是哪个版本』）
- git branch --contains <运行commit>（或 rev-list HEAD..运行commit --count）：判定运行版本是否包含特性提交、落后几个（解决『部署了吗』）
- 核对验证证据形态（fixture 单测 vs 真实包冒烟），三层各挂一条记录后成稿并停止

## Stop conditions
- 实现/部署/验证三层各有一条权威记录支撑（commit hash、文档节、generation 数字）
- 某层无对应权威记录（无运行时面/无部署概念）→ 该层显式标注『不适用/未核』，不由其它层推断填充

## Verification
- 『已部署/可使用』必须由祖先关系或代际比较算出，禁止从『代码已合入』默认推出
- 阶段结论使用设计文档自身的出口口径表述，不改写、不降标准
- 每层结论可回指到具体记录（hash/文档行/generation），无记录的层显式声明

## Counterexamples
- 纯库/CLI、无运行服务面的『能用吗』：只需实现+测试两层，不要硬造部署层检查
- 提交信息不含特性关键词（squash 提交或工作尚未 commit）：git log 不是索引，此时关键词文档/文件搜索才是正确开局
- 用户只问『代码里是否已实现』：到实现层即停，不做运行时与验证核对
- 服务状态回执的 generation/lag 列表混有其它 target（如 feishu/all）：不得拿无关 target 的代际对目标服务下结论
- 运行 commit 与 HEAD 无祖先关系（分叉部署线）：branch --contains 结论无效，需改用 merge-base/发布记录核对
