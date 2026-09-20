---
method_id: claim-literal-anchored-two-sided-verification-337b9ae43101
name: claim-literal-anchored-two-sided-verification
description: 验证含具体可检字面量（提交 SHA、错误码、格式前缀、digest 字段名、计数）的技术声明时，把声明自带的字面量当作最窄探针：远端 API 核冻结 ref；commit 作用域 diff 核'零 production 修改'，branch 级差异用机器记录里的 base SHA 归因为既有栈；grep 失败码字面量直接落在不变量检查点，再沿检查点暴露的标识符 provenance 走到生产端构造点，两侧独立复现比对后即停，不做宽泛正则的全目录枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:2522:a92cf788d95a9b684506
evidence_refs: learning:learn:2be339f2710d
created_at: 2026-09-20T13:57:39.862929+00:00
updated_at: 2026-09-20T13:57:39.862929+00:00
---
## Trigger
审查/复核一个提交或结论声明，且声明与机器记录中已含精确锚点字符串（精确 SHA、失败/错误码字面量、哈希格式前缀、digest 字段名、base SHA），需要独立验证根因与边界声明是否属实。

## Discriminator
在进入任何源码搜索之前，声明与机器记录（如 LIVE-RESULT.json）已暴露精确锚点：失败码 browser_target_precondition_mismatch、`target:` 格式前缀、base_s5_sha。任一锚点一次精确 grep 即可落在不变量检查点或生产/消费一侧，当时就足以把'扫描全 src 找哈希逻辑'缩成'定位两侧各一行并比对'。

## Short path
- 远端 API/git ref 核对声明中的精确 SHA 与 ref 冻结（未知量：冻结是否真实、main 是否未动）
- git show <commit> --stat 核 commit 作用域改动；branch-vs-main 的 src 差异用机器记录中的 base SHA 归因为既有栈，分开陈述两种口径（未知量：'零 production 修改'按哪个口径成立）
- 读机器记录（LIVE-RESULT.json 等）逐字段核对声明，并从中提取失败码等可用锚点（未知量：声明与机器记录是否一致）
- grep 失败码字面量定位不变量检查/失败 raise 点（未知量：执行端实际对什么做哈希）
- 沿检查点暴露的 digest 字段名/标识符（如 browser_target_id_sha256、page_token）grep 到生产端构造行，两侧格式独立比对（未知量：绑定端实际对什么做哈希）
- 复跑冻结的最小 adjudication 测试并核对边界声明（无 PR/deploy、worktree clean），全部锚点核对完毕即停

## Stop conditions
- 两侧代码事实已独立复现（生产者构造行 + 消费者哈希行 + 失败码触发行三处坐标齐）且与机器记录互证，根因声明属实或被证伪
- 任一声明锚点（SHA、错误码、计数）与权威来源不符：转为报告偏差，不再继续枚举候选
- commit 作用域 diff、branch 归因、无 PR/deploy 等边界声明全部核对完毕

## Verification
- 根因结论必须同时给出三处代码坐标：生产者 token 构造行、消费者 digest 行、失败码触发行，且格式差异可由任一人按行号复算
- commit-scoped 与 branch-scoped 的 src diff 分开陈述，branch 差异附 base SHA 归因，避免'零 src 修改'被误读为'分支无 src 差异'
- 冻结测试本地复跑结果与记录中 validation 块一致；远端 ref、worktree HEAD、无 open PR 三者交叉一致

## Counterexamples
- 声明只含叙述（如'两边哈希不一致'）而无任何字面量锚点：literal-anchored grep 不可用，需退回结构化发现（按模块/字段设计走）
- 失败码字面量在多处 raise 或只定义在共享错误模块：grep 落到定义而非检查点，应改 grep raise 位置或结合调用链
- 待验证的是运行时行为（竞态、真实浏览器状态）而非静态不变量：静态两侧复现只能给出'静态证据支持'，不能宣称已验证；若冻结协议禁止重跑，更须显式标注证据级别
- 声明中的字面量 grep 无命中：应视为声明可疑的负证据并上报，而不是放宽正则继续全库扫描
- 审查目标是整个分支历史质量而非单条声明时，仅做 commit 作用域 diff 会漏检，此方法不适用
