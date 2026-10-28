---
method_id: ambient-env-differential-probe-on-self-hosting-runtime-review-c64e81b40446
name: ambient-env-differential-probe-on-self-hosting-runtime-review
description: 对会自举派生子进程/web终端的 runtime/harness 仓库做批量变更审查时，若 git log 显示多数提交自带门禁/测试回执，则静态重读这些已验证 diff 的边际价值极低；现有门禁结构性覆盖不到的唯一面是『代码在部署运行时环境变量下执行』的结果。方法：用仓库自己的定向测试切片做单变量两跑对照（运行时注入的产品前缀环境变量在场 vs 剥离），确定性差异即指向环境状态泄漏/env 压过 cwd 的优先级反转类 bug，再沿涉事变量名读配置解析代码定位，输出测试隔离+优先级修正双修复。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f14553ff-29f5-4d15-a5a8-ee029c618df1:2:bb3d10076ba66d9a000b
evidence_refs: learning:learn:2c9d5990a5af
created_at: 2026-10-20T20:43:00.041364+08:00
updated_at: 2026-10-20T20:43:00.041364+08:00
---
## Trigger
用户要求审查一个自举式 runtime/agent-harness 仓库的『最近更新』批量提交，且满足：产品本身会 spawn 继承其环境变量的 shell/子进程；审查可在运行时派生的环境中进行（或可模拟）；git log 提交信息大多自带测试计数/独立审查 PASS 回执

## Discriminator
审查起点即可见两条事实：(1) 提交信息携带自己的门禁回执（测试计数、reviewer 通过），说明静态重读这些修复 diff 只是在重复已跑过的门禁；(2) diff 涉及配置/workspace 解析与 runtime identity 区域，而运行时给所有派生 shell 注入产品前缀环境变量——这是干净 CI 与 diff 阅读都覆盖不到的执行面，只有在该环境在场/剥离的对照下才暴露

## Short path
- 用 git log --since + diffstat + CHANGELOG 量化审查范围并建立版本叙事
- 按回执把提交分两类：自带门禁回执的修复（静态重读边际价值低）vs 横切性配置/runtime-identity 变更（环境交互风险高）
- 对高风险类，取仓库自身定向测试切片做单变量两跑：一次带着运行时注入的产品前缀环境变量（运行时派生 shell 的原生环境），一次剥离这些变量
- 出现确定性差异 → 沿涉事变量名读配置解析代码的优先级（如 env 取值压过 cwd、存在即视为显式指定）确认泄漏机制
- 在无关 cwd 用只读 CLI smoke 复现产品侧影响（错误 workspace 解析或硬失败），报告双修复（conftest/测试隔离 + 优先级调整）与 CI 环境对照 job 建议

## Stop conditions
- 同一切片两次运行结果完全一致（无随变量在场的确定性差异）→ 该面无泄漏，停止此假设
- 失败呈时序敏感/偶发而非随环境变量确定性翻转 → 转入稳定性轨道，不按泄漏追查
- 失败发生在收集/导入阶段（ModuleNotFoundError 类）→ 转入既有权威解释器方法处置，不当作产品缺陷
- bug 已经测试对照+CLI smoke 双重复现且修复点定位 → 停止扩展探测，撰写审查结论

## Verification
- 同一切片只切换目标环境变量、其余不变，确认失败随变量在场/剥离一一对应
- 在运行时派生 shell 中确认该变量确实被注入且取值指向部署快照目录而非用户工作区
- 在无关目录（如 /tmp）用只读查询命令人工复现错误解析或硬失败现象
- 剥离变量后同一切片全绿且数字与提交回执声明的基线一致

## Counterexamples
- 纯库仓库、不为子进程注入产品环境变量 → 差异探测无产出，不必搭建对照
- 该环境变量是文档化的显式覆盖且运行时在 spawn 前已主动剥离 → 在场差异属设计行为而非 bug
- 用错解释器导致的收集错误（缺依赖模块）→ 按既有项目权威环境方法解决，勿误报为产品缺陷
- 批量极小（个位数提交）且无回执 → 直接读 diff 已是最短路径，先建环境对照反而绕远
