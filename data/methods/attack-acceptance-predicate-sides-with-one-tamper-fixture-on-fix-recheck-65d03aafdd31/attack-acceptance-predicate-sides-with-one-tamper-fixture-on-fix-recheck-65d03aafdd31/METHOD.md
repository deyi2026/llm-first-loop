---
method_id: attack-acceptance-predicate-sides-with-one-tamper-fixture-on-fix-recheck-65d03aafdd31
name: attack-acceptance-predicate-sides-with-one-tamper-fixture-on-fix-recheck
description: 复审一批安全/门禁修复时，把每处修复自身的『接受谓词』当作下一个未知量立即攻击：匹配是精确集合成员/全等，还是前缀/子串？等式比对覆盖了哪几侧（main 与 candidate、哪些 ref/blob）？读到『宽松匹配×单侧比对』的瞬间，构造最小两侧篡改夹具（可信侧原样、篡改侧沿漏比的那条边改动，如把 policy 钉到 gate 集合外路径），在审计树外的隔离副本运行判定函数——返回放行终态即坐实为可复现发现；谓词精确且对称才转入广度确认。签发裁决前复核冻结锚点（HEAD+status），漂移即退回只读 git 对象审冻结 SHA 并要求重新冻结。以此替代几十轮 happy-path 广度确认后才碰真洞的走法。
aliases: 复审修复先审比对哪几侧, 单侧校验绕过复现, 白名单前缀匹配放行, 修复验证别只走happy path, policy钉集合外路径自审批, 终审前复核冻结SHA漂移
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:3ace7aea-bf9b-4b21-a758-09fc31897ce7:89:f6a1aa345fe0710929f8
evidence_refs: learning:learn:78e431beed0c
created_at: 2026-11-17T00:51:56.892101+08:00
updated_at: 2026-11-17T00:51:56.892101+08:00
---
## Trigger
复审一批已声明的安全/门禁修复（每条修复=在校验点新增比对、白名单或引用对照），尤其当修复清单来自上一轮 P0/P1 裁决、需要同时确认『确实修了』与『没留新洞』时；或用户下达收口指令要求基于既有证据立即出终审裁决。

## Discriminator
修复源码在被读到的那一刻就已暴露两个可审属性：①接受判定的匹配严格度——精确集合成员/全等（path in _SET、逐字节 blob 相等）还是前缀 startswith/子串/存在性；②比对的对称性——等式/哈希校验覆盖了哪几侧（main 与 candidate、哪几个 ref/blob）。任何『宽松匹配×单侧比对』组合直接定义出一条可篡改边：外部方（如 policy）可把引用钉到集合外路径，并只改未被比对的那一侧。该判别不需要任何后续探索，读修复时即在手。

## Short path
- 开局钉冻结锚点：记录 HEAD SHA 与 git status 是否 clean（未知量：审查对象边界）
- 逐条读修复点；每读一处立即审其接受谓词的严格度与对称性，而不是先做 happy-path 广度确认（未知量：这处新检查自身是否留洞）
- 命中『前缀式接受』或『单侧比对』→ 构造最小两侧夹具：可信侧保持原内容，篡改侧沿漏比的那条边改动（如 policy 钉到 gate 集合外路径、只改 candidate 侧文件），在审计树外的隔离副本运行判定函数（未知量：该洞是否真能放行）
- 判定函数返回放行终态（ELIGIBLE/PASS 类）→ 坐实为可复现发现，记录精确 file:line 与仓库外复现件；返回 HOLD/拒绝 → 该修复判定为已关，才转入下一条或广度确认
- 签发裁决前复核锚点（HEAD+status）；若漂移且文件 mtime 早于自身任何写窗口 → 判并发写入：审查面退回冻结 SHA（只读 git 对象），漂移本身单列为完整性发现并要求重新冻结后再终审
- 输出：P0/P1/P2 计数+逐条 file:line+先前修复已修/未修对照表；无法验证的点保守列 HOLD/REVISE，部署/线上事实与代码结论分开陈述

## Stop conditions
- 每处宽松/不对称谓词均已用一次夹具复现或被证伪，不存在未攻击的谓词洞
- 用户所需裁决（PASS/REVISE+分级+file:line）已能由已取得证据与复现件完全支撑，停止新增工具探索
- 终审锚点复核通过：HEAD=被审 SHA 且工作树 clean；否则只输出有条件裁决并要求重新冻结新 SHA

## Verification
- 夹具运行于隔离副本（如 /tmp 克隆、-p no:cacheprovider、禁写字节码），事后复核被审树 git status 仍 clean，复现件写在仓库外
- 复现方向与谓词读出的漏洞一致：仅改动『未被比对的那一侧/集合外路径』即获得放行终态
- 每条发现附精确 file:line；先前修复逐条给出已修/未修结论；无法验证的部署侧事实显式 HOLD，绝不冒充已部署/已验证

## Counterexamples
- 修复谓词本就精确且双侧（路径 ∈ 集合且逐条 blob(main)==blob(candidate)）→ 无不对称边可攻，直接过下一条，不必硬造夹具
- 纯功能/文案类修复，或读代码即可判定正确性且夹具成本远高于收益 → 不适用
- 复现需要真实外部不可伪造凭据（如 GitHub App 私钥、生产 API 事实）→ 只能静态审计并保守 HOLD，不得声称已复现
- 门禁没有外部可钉引用面（policy 只能引用被双侧比对的集合内路径）→ 前缀式接受不构成实际通道，应降级为防御纵深备注而非 P1
