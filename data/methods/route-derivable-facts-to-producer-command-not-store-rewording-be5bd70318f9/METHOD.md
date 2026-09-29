---
method_id: route-derivable-facts-to-producer-command-not-store-rewording-be5bd70318f9
name: route-derivable-facts-to-producer-command-not-store-rewording
description: 会话 Evidence/capture 库只缓存本会话已捕获的工具输出；自由文本检索结构上无法命中尚未捕获的内容，对同一未知量换措辞连续检索只会线性烧调用。当未知量是本地可确定性推导的统计量（tracked 文件数、代码行数、目录体积、ignore 状态等）时，权威来源是能直接产出它的命令本身：跑一次，回执即成为可引用证据。库检索只保留给『回查过去的观察』；『当前会话 Evidence 未找到匹配』应读作『未捕获』，而非『不可知』。把『N 种措辞 × 全库存』的枚举缩成一次命令产出。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc07ea9d-6ab9-44b7-b385-65eea54960b6:87:ddc8017f9e42e2078575
evidence_refs: learning:learn:b126affee2d5
created_at: 2026-09-28T09:51:06.999227+08:00
updated_at: 2026-09-28T09:51:06.999227+08:00
---
## Trigger
对一个未知量取数时：已对 session evidence 库发出至少一次自由文本检索且 miss（回执形如『未找到匹配…的当前会话 Evidence』），且该未知量属于本地可确定性推导量（计数/体积/状态类）；或即将对同一库第二次改写检索词重试同一未知量。

## Discriminator
miss 发生时已可见的两条事实即可缩空间：(1) list_evidence 已枚举会话捕获清单（可见来源仅 web_fetch(GitHub) 与 execute_command），其中不含目标统计量；(2) 目标量（tracked 文件数、.py 总行数等）由 git/文件系统单条命令即可确定性产出——对尚未捕获的确定性事实，库检索必 miss，miss 只证明『未捕获』，不证明『不可知』。

## Short path
- 把未知量写成可判定形式（如 tracked 文件数、.py 总行数），先判定类别：确定性本地可推导 vs 依赖过去捕获。
- 判定为确定性可推导 → 跳过库检索，直接构造产出它的单条权威命令（git ls-files / wc -l / du / check-ignore 类）并执行，回执自动落为可引用证据。
- 从命令回执直接读数并引用该 evidence ref 进入写作；不再对同一未知量改写检索词。
- 若数字要进书面结论需交叉核验，用第二类独立机制（不同命令/来源）核对一次，而不是继续检索重试。
- 仅当未知量是『过去某次观察的值』（此前抓到的 README/release 内容）时才走库检索，命中后按 ref 水合。

## Stop conditions
- 权威命令回执已直接包含目标数字/状态（coverage=source_complete），取数完成。
- 交叉核验用了一类独立机制且结果一致，验证完成。
- 判定该事实依赖过去捕获（如 volatile 网页内容的历史值）→ 切换到库检索/按 ref 水合，本方法停止。

## Verification
- 最终数字的 evidence ref 来源是直接产出该量的命令（execute_command、source_complete），而非对无关捕获的推断。
- 该 unknown 上的 search_evidence 调用数 ≤1（仅当确需回查已捕获内容时为 1，否则 0），不存在同义改写连续 miss。

## Counterexamples
- 目标事实是对易变远程资源的过去观察（如某次 release 页面内容）：库检索才是正确通道，重跑命令拿不回历史值。
- 首次检索前不确定库里是否已有捕获：允许一次检索试探；本方法约束的是 miss 后对可推导事实继续改写重试。
- 事实依赖远端当前状态且无本地命令可产出（如上游最新版本号）：应 fetch 权威 URL，收到重复抓取提示后停止，而非改写重试。
