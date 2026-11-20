---
method_id: adjudicate-observed-gaps-via-manifest-declared-install-order-5f6d9b4e51e1
name: adjudicate-observed-gaps-via-manifest-declared-install-order
description: 审查分阶段/一次性安装的治理或门禁变更（required checks policy、bootstrap PR、准入资格）时，权威面实测与候选声明目标态的偏差（保护规则缺一个 required context、冻结 SHA 远端 422、组件未部署）不自动构成缺陷。判别器：被审 artifact 自身 manifest/summary 是否已显式声明该维度的安装顺序，且声明先于观测被读入、前提事实可机械核验（PR MERGED 且 mergeCommit==base）。声明覆盖且前提成立 ⇒ 预期中间态，不计数；无声明或前提被证伪 ⇒ 缺陷，转 REVISE/越权审查。裁定须同时锚定声明行号与前提机械事实，禁止用候选文件自我描述兜底；终报分缺陷计数、环境不可达事实声明、资格前提三层，同时防『误 REVISE』与『借口化 PASS』两个方向的失败。
aliases: required check还没配上算不算REVISE理由, 先合并后补保护的安装顺序, 冻结提交在远端422查不到, 实测和manifest声明对不上, 门禁策略审查中间态裁定
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:cade79be-b36b-405e-8b3d-1ac335259907:0:ca513dd4365d70c02cfa
evidence_refs: learning:learn:1e05def832bf
created_at: 2026-11-17T01:39:25.309707+08:00
updated_at: 2026-11-17T01:39:25.309707+08:00
---
## Trigger
只读审查一个带声明安装顺序的治理/门禁变更，核验中权威面（分支保护、远端 API、部署状态）实测状态与候选声明目标态出现偏差，需要裁决这是缺陷还是声明的中间态。

## Discriminator
偏差维度是否被被审 manifest/summary 的顺序声明覆盖（knowledge-at-time：声明须在偏差观测之前已读入），且声明前提可机械核验成立（如 PR state=MERGED 且 mergeCommit 等于当前 base）。声明存在、覆盖该维度、前提成立三者齐备 ⇒ 预期中间态；任一缺失 ⇒ 缺陷。

## Short path
- 先读齐变更文件全文，把 manifest 声明的目标态、安装顺序、回滚路线当作后续偏差的分类器提前装载
- 把 policy 逐 pin 对到候选不可修改的独立权威面（base git blob、workflow id API、check-runs app 集合、保护规则 contexts、PR merge 元数据），一条命令聚簇多面
- 遇实测偏差：先查 manifest 是否声明该维度的阶段顺序；一致且前提机械成立 ⇒ 记为预期中间态并在终报说明；否则记缺陷并附 file:line/API 证据
- 终报三层：P0/P1/P2 缺陷计数、环境不可达外部事实的显式声明、资格/HOLD 前提重申

## Stop conditions
- 每个受审核验点均有权威面证据或明确归类（缺陷 / 声明内中间态），无悬空项
- 每条中间态裁定同时具备声明行号与前提机械事实两个锚点
- 不可达外部事实转为终报声明，不再消耗调用去探查

## Verification
- 抽取 manifest 原文声明顺序的行号引用，与偏差维度逐一对照
- 机械核验声明前提（mergeCommit==base、PR MERGED、祖先关系），不接受叙述性声明自证
- 反向自检：若删去声明行号该偏差是否仍会判缺陷？若是，说明此前裁定依赖了自我描述而非独立证据

## Counterexamples
- manifest 未声明该维度顺序，或 policy 声称『已全部生效』而保护规则实测缺失 ⇒ 声明与实测矛盾，是缺陷而非中间态
- 声明前提被证伪（PR 未合并、mergeCommit 不等于 base）⇒ bootstrap 资格声明失效，转越权/REVISE 审查
- 偏差发生在 pin 值本身（如 blob SHA 与 main 真实对象不符）⇒ 与分阶段无关，直接判缺陷
- 偏差维度在 manifest 中完全未被提及 ⇒ 本方法不适用，按普通缺陷或未知项处理
