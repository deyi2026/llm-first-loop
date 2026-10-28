---
method_id: anchored-grep-and-symbol-existence-first-for-named-contract-verification-384210dfcc3c
name: anchored-grep-and-symbol-existence-first-for-named-contract-verification
description: 验证/审计类请求逐项点名了精确可 grep 的字面量（schema 标记串、函数/契约名、路径、命令、期望大小/哈希）时，把每个点名未知量映射为一次带明确 glob 的 grep / git grep 定点探针，而不是先跑全库内容搜索去扫 README/CHANGELOG/evals 等产物树。被要求『按某命名契约/入口验证对象』时，第一探针应是符号存在性（工作树 src/、git HEAD、worktree 三处）；零命中本身是一等发现——如实报告『该命名契约不存在』并在仓内定位真实等价契约完成替代核对，而非假装置已对照原契约通过。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25393690-39c2-43d8-b50f-3157a58aaea2:2:520c3210de5d7bc7b72c
evidence_refs: learning:learn:18718021479d
created_at: 2026-10-15T00:09:33.374715+08:00
updated_at: 2026-10-15T00:09:33.374715+08:00
---
## Trigger
请求本身枚举了逐项待核实的精确标识符或期望值（标记串、符号名、路径、命令、哈希），且仓库存在已知存储约定（事件日志目录、源码目录）；或被要求按某个命名契约/入口做核验，而该契约是否真存在于当前代码树尚未确认。

## Discriminator
请求文本中已出现可直接 grep 的字面量锚点，且回执或 README 已显式给出相关数据的权威落点（如『data/event_logs/<session_id>.jsonl 为事件单一真相源』、代码契约在 src/ 下）。这两个当时已知事实即可把候选来源从『全库任意文件』缩为『已知目录中含该字面量的少数文件』，宽域内容搜索既慢（本集两次 60s 超时）又只产出噪声命中。

## Short path
- 先用请求自带的命令+期望值完成可机械核对项（如 staged diff 的字节数/SHA-256），一项一命令，立即定格该项结论。
- 对每个点名标识符做定点探针：grep -l '<schema标记串>' data/event_logs/*.jsonl 定位承载文件；grep -rn 'def <符号>' src/ 与 git grep -n <符号> HEAD（含 worktree）探符号存在性。
- 用 event_stream scope 或时间戳最新者确认当前会话身份，再从对应 jsonl 一次性提取目标事件的完整字段树（含 payload.metadata 内层），核对全部契约字段。
- 符号三处零命中时立即定格为发现：报告『命名契约/入口不存在，正式流程第 N 步按字面不可执行』，转而用相邻名 grep 定位仓内真实等价契约（同职责的 assurance/reviewer 模块）做替代核对，并显式声明差异。
- 仅当字面量锚点缺失、或定点探针无法解释目标内容时，才扩大到全库内容搜索/语义检索。

## Stop conditions
- 用户点名的每一项均已被权威落点的直接工具回执证实或证伪（含『符号不存在』这类否定性结论已固定为发现）。
- 目标事件完整字段树与等价契约源码均已取得，足以支撑逐项结论+下一阻断的排序报告。
- 遵守请求附带的只读/禁写约束，未因核验需要而触发任何被禁止动作。

## Verification
- 最终报告中每条结论都能指回一次具体工具回执：jsonl 字段值、grep/git grep 的命中行或明确的零命中、门禁源码行号。
- 否定性结论（命名符号不存在）须给出至少两处权威范围（src/ 工作树、git HEAD，另加 docs/scripts/worktree 更佳）的零命中证据，而非单点 miss。
- 替代契约核对须说明真实等价物与原命名契约的对应关系及已知差异（如 git 历史中的 activation hold 记录）。

## Counterexamples
- 请求只描述行为/症状而无任何精确标识符（无字面量锚点）时，定点 grep 无从下手，宽域或语义检索才是正确第一步。
- 符号可能定义在 vendored/生成代码或运行时注入中，仅 grep src/ 会误报『不存在』；须先确认代码布局再下否定结论。
- 小型或已建索引的仓库中全库搜索廉价且快，强制换成多段 grep 反而增加调用数、无收益。
