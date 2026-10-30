---
title: 冻结产物头部序列化：fail-closed 往返自检 + 并发写者下的预检提交
scenario: 修复冻结产物头部字段粘连缺陷（EVO-20261030-109d7068）：旧实现把 push_remote_base 与 frozen_head 拼在同一行；同一文件另有一个并发会话的未提交 WIP，且仓库有“函数尺寸只降不升”棘轮与提交前缀白名单。
root_cause: ""
solution: "1) 头部改每字段一行 key=value，并同时实现严格解析器（fail-closed：值内空白、值以 \"<key>=\" 开头、重复键、键名非法一律拒绝）；2) 生成侧对“组装完成后的 material 头部块”做一次往返自检，解析结果必须与预期字段完全相等，否则抛错在出票前拒绝（审查子进程不启动）——即“应拦输入”必须经真实入口实测；3) 并发写者：先比对 git diff 的 @@ hunk 边界确认不重叠，只暂存自己那三个文件；4) 被改函数命中 R9 棘轮时把逻辑抽成模块级 helper（193→173 行），顺带修掉他人遗留的越线；5) 提交前用 git write-tree + git commit-tree 合成临时提交对象跑 scripts/r9_commit_check.sh 预检（不移动 ref），前缀须落在白名单内（如 fix(r9):）。"
evidence: "提交 5002688c3；测试回执 evidence://v1/02035daa1f31f256d3690e853b94bb86231ad9f6e6d0942b9648296e08c9f5d7（156 passed）、evidence://v1/8735a9847c171a4bded0cb02a40855b211547fa961641cbe7a880b7322f8da20（r9_commit_check 五规则 PASS）；证据文档 docs/EVO-20261030-109d7068-frozen-header-roundtrip.md"
tags: [admission-gate, serialization, fail-closed, concurrent-writer, r9-ratchet, git]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T16:19:20.848834+08:00"
updated_at: "2026-10-30T16:19:20.848834+08:00"
supersedes: [EXPERIENCE-20261027-冻结补丁候选-host-准入-原版-r9-的三条操作纪律-核对-命令-还原]
---