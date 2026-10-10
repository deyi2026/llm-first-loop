---
method_id: read-gate-rules-before-first-gated-submission-8c221f6f9573
name: read-gate-rules-before-first-gated-submission
description: 当操作要经过仓库本地的校验包装脚本（提交门禁、部署 gate、lint 包装）提交，而其规则（前缀白名单、文件面限制、标记要求）尚未读过时，先读一次门禁/检查脚本的规则段，把全部规则枚举出来再构造首批参数；并把完整规则集应用到同批次每个后续提交上（按规则预拆分文件集）。依据：失败回执每次只暴露第一条违规规则，脚本一次给出全部规则；每个 gate 失败消耗完整校验周期（锁、机检、ci_gate）。本集第一次提交因 fix(extensions) 不在白名单而整轮 gate 作废；事后读脚本才发现规则④会同样击落提交 B（feat 触碰 tests/guards/*.json），提前拆成 guard(r9) 才免于第二次整轮失败——这次阅读本可发生在首次提交之前。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:64924088-0141-4a3a-87ee-81f09678620d:484:1e83e5c09d19a5f1c4fa
evidence_refs: learning:learn:101319175d8b
created_at: 2026-10-10T10:45:52.509245+08:00
updated_at: 2026-10-10T10:45:52.509245+08:00
---
## Trigger
即将通过仓库本地校验包装脚本提交操作（如 bash scripts/xxx_commit.sh / deploy gate），提交的消息或文件集需满足其校验规则，但规则清单尚未读过；尤其当计划多个连续 gate 提交时。

## Discriminator
命令行中已出现包装脚本路径，且该脚本文件头/用法明确声明承载机检、门禁或规则检查——规则在首次提交前即可零失败成本地枚举；而失败回执每次只揭示第一条违规，重试成本是一次完整校验周期。

## Short path
- 从待执行命令中识别校验包装脚本路径（本集：bash scripts/r9_commit.sh）
- 首次提交前读/grep 一次该脚本及其调用的 check 脚本的规则段，枚举全部规则（本集：规则①前缀白名单 + 规则④守卫文件前缀保护等五条）
- 按全部规则构造消息与文件集并逐条自检（fix(extensions)→fix(r9)；feat 不触碰 tests/guards/*）
- 把完整规则集套用到批次内每个后续提交：据此把守卫基线提前拆成独立 guard(r9) 提交，再提交 feat 主体

## Stop conditions
- 计划的消息+文件集已逐条通过枚举出的全部规则，可直接提交
- 规则本地不可枚举（脚本无规则段、规则在远端 CI）→ 放弃预读，改用最小探针提交策略
- 批次内所有 gate 回执均为 PASS，无任何 rule-FAIL

## Verification
- grep/读取产出明确的规则清单文本（白名单行、规则编号、例外条款），而非凭印象猜测
- 首次及批次内每次 gate 回执为 PASS；规则违规计数为 0
- 每个拆分后的提交单独对照规则清单复核（如 guard(r9) 提交只含 tests/guards/*.json）

## Counterexamples
- 包装脚本不承载规则（规则只在远端 CI 或口头约定，本地读不到）——不可套用，改用最小探针提交探规则
- gate 周期极廉价且失败回执一次性枚举全部违规（部分 linter 全量报错）——此时一次失败信息量等价于一次预读，预读无收益
- 同一 gate 的规则已读过且脚本未变更的重复提交——机械重读脚本是浪费，直接复用已有规则清单
