---
method_id: adversarial-review-evidence-escalation-for-fail-open-decision-logic-04c7e1815c0f
name: adversarial-review-evidence-escalation-for-fail-open-decision-logic
description: 交付物是『解析后决定放行/拒绝』的判定层（allow/deny 编译、命令/路径守卫、拦截正则/阈值）时，全量测试绿+quick gate 只是已知向量覆盖证据——测试与代码共享同一心智模型，测不出词法边界缺口（引号分隔符、跨行引号、$'…'/算术展开、续行、子shell）。宣称『完成/已生效』前必须取得独立对抗审查在同产物指纹上的 P0=0 PASS；审查 REVISE 挖出的每条 fail-open 是向量命中而非流程摩擦，逐条修复+补回归用例后重审。未过审查时宣称措辞封顶为『已知向量未漏/代码已提交』。
aliases: 测试全绿也别急着宣布安全闸修完, 守卫代码要找人专门构造绕过用例, 引号和续行能绕过命令拦截器, 声明禁止却实际放行的暗坑, 绿灯只说明已知向量没漏
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:fb85cea0-beb4-424d-b482-2819180ee46f:876:57ec79d4df5f2cdb5c66
evidence_refs: learning:learn:c219a2ba2269
created_at: 2026-10-31T19:00:25.881369+08:00
updated_at: 2026-10-31T19:00:25.881369+08:00
---
## Trigger
对解析后决定放行/拒绝的安全或授权代码（scope guard、deny 清单、命令判定、拦截判据/正则/阈值）准备宣称完成或已生效，且当前证据只有全量测试绿/quick gate 通过

## Discriminator
diff 内容本身已显示产物是『解析→放行/拒绝』决策面而非纯功能代码，且仓库规则文本（审查工具 schema、门禁脚本头部）已明示门槛类变更未经实测拦截只可称『代码已提交』——这两条当时即可见，足以把证据需求从『再跑测试』升级为『构造新向量的对抗审查』

## Short path
- 宣称完成前先给产物定性：是否『决定放行与否』的判定层？是 → 证据等级升级
- 把绿测试降级为必要条件；下一未知量=能否构造测试集之外的新攻击向量
- 启动独立对抗审查（或自查时按词法边界显式枚举：分隔符引号形态、跨行引号、$'…'/$VAR/~ 展开、算术左移、续行连接、子shell 分组）
- 每轮 REVISE 的 P0 fail-open 视为向量命中：逐条修复并补回归用例，同产物指纹重审
- 同 SHA 的 P0=0 PASS 回执 + 全量门禁 = 完成证据；在此之前对外宣称上限是『已知向量未漏』

## Stop conditions
- 独立审查在当前产物指纹上 P0=0 并取得 PASS 回执，且全量门禁通过
- 产物被证伪为非决策面（纯展示/数据/功能代码），常规门禁绿即足

## Verification
- 审查 PASS 回执绑定的产物 SHA 与最终交付物一致
- 每条审查 P0 在测试套中有对应新增回归用例
- 最终报告措辞与证据等级匹配：有实测拦截才说『已生效』，否则只说『代码已提交』

## Counterexamples
- 纯功能/展示代码（UI、报表、文档生成）：全量测试+门禁绿已足，对抗审查属过度成本
- spec-by-test 且向量空间封闭的场景（纯函数穷举表判定）：已知向量即全空间，绿测试即完备
- 审查者只重跑同一测试套、不构造新向量：不产生增量证据，等于未升级证据等级
