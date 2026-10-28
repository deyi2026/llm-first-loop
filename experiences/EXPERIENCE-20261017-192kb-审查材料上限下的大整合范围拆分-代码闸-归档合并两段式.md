---
title: 审查材料超限下的大整合范围拆分（历史上限 192KB，现行 2.5M 字符）：代码闸+归档合并两段式
scenario: 【历史现场，2026-10-17 当时上限 192KB】大范围分支整合需过 RULE-AI-28 全量测试审查准入，整合 diff（代码+大量证据 docs）超过当时上限被拒；现行 2.5M 字符下同类整合通常可一次过门，拆分原则只在逼近上限时使用
root_cause: ""
solution: 审查范围拆分（scope split）：代码+台账+SoT 入代码闸（材料压至上限内、审查者可见 100% 代码增量），纯证据 docs（回执/结果/计划，测试零依赖，先做交集核验）拆出为独立归档分支，代码合并后再以 docs-only 分支过 merge-gate 落地；拆分提交与归档提交互相显式引用源树 SHA。
evidence: "evidence://v1/0f9faf568a534aa411f8aa686c7256c60bebbd19bab232cb1381356238dd8a96"
tags: [rule28, review-admission, merge-gate, scope-split, branch-integration]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-17T02:40:43.289504+08:00"
updated_at: "2026-10-17T02:40:43.289504+08:00"
---

> **当前适用性（2026-10-28 复核）**：审查材料上限已从 192KB 提高到 **2.5M 字符**（超限码 `review_artifact_exceeds_cap`）。"范围过大就按测试依赖切分"仍是有效原则，但触发阈值变成 2.5M：下文的 338KB→41.9KB 只是当时案例，不是当前必须达成的目标，也不该为凑旧阈值拆分本来能一次过审的整合。

场景：RULE-AI-28 Host 审查准入绑定材料 = diff(merge-base(HEAD,main), HEAD) + 未提交 + 未跟踪；当时上限 192KB（现 2.5M 字符）。超过当前上限会以 review_artifact_exceeds_cap 被确定性拒绝，且改写命令形态（重定向/复合命令）无法绕过（另触发 compound_protected_shell_requires_split_commands）。
方法：按"测试/契约依赖"切分审查范围——(1) 计算并集测试读取的 docs 路径集与分支新增 docs 路径集的交集；(2) 交集为空 ⇒ 全部 docs 增量从闸分支 git rm 拆出（提交注明来源树 SHA），代码+台账（.codeartsdoor ledger 等 SoT 数据）入闸；(3) 拆出 docs 在代码合并后经独立 docs-only 分支（源树 checkout，字节级零改动）单独过 merge-gate 落地，履行"挂起义务"记录。
验证：F批整合（338KB→41.9KB 材料）两轮准入 REVISE→修复→PASS，全量 R9 9228 passed；两道 merge-gate 均 PASS 且预判 ff SHA 逐字符一致（27d4d009e/b68dbc2a5）。
边界：仅当 docs 增量与代码增量可干净分离且无契约耦合时适用；拆分提交必须显式记录源树地址与零改动承诺，由 gate 审查者对源树做字节级 diff 核验。