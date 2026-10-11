---
method_id: dump-one-full-record-before-log-extraction-scripts-351eec511bcf
name: dump-one-full-record-before-log-extraction-scripts
description: 从结构化事件日志/JSONL/表聚合失败原因时，若本会话尚未完整读过目标事件类型的任何一条完整记录（字段名、取值词表只见于截断输出），先完整打印一条代表记录（优先失败样本）确认真实 schema（如 outcome 词表、error_type 字段位置），再写聚合脚本：group-by 用实际字段，筛选用已提取的稳定 ID（如失败 call_id 列表）而非时间字符串运算。避免空提取、KeyError/ValueError 迭代与过滤词表猜错。是 repo-api-discovery 在运行时数据面的类比，但对象是日志记录而非源码 API。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8bc1cbb3-5fe5-44cb-9818-3acb329d2acb:565:719f31ec34f1e4553a2b
evidence_refs: learning:learn:903a2398cd55
created_at: 2026-10-11T18:30:20.661661+08:00
updated_at: 2026-10-11T18:30:20.661661+08:00
---
## Trigger
需要从结构化事件日志/JSONL/数据库提取或聚合失败原因，而本会话只见过该事件类型的截断/部分载荷、尚未完整读过任何一条目标记录；典型信号：开始手写带猜测词表的过滤脚本（如假设 outcome='completed'），或用时间字符串算术圈选记录。

## Discriminator
目标日志是结构化 JSON 记录且单条完整记录可随时读取——所需字段名/取值词表在任何批量脚本之前即可由一次 record dump 观察到。本集当时输出已显示载荷被截断（如 'attempt_k' 被切）且 outcome 词表仅部分可见（只见 'interrupted'），说明 schema 未被完整观察，先 dump 一条即可消歧。

## Short path
- 定位权威结构化日志与目标事件类型（如 provider.transport.settled 失败记录）
- 先完整打印一条目标类型记录（优先失败样本、禁止截断），读出真实字段名与取值词表
- 聚合脚本只用已观察到的字段做 group-by（如 Counter(outcome)，无需猜词表）；只按已提取的稳定 ID（8 个失败 call_id）筛选，不做时间戳字符串算术
- 由真实字段（error_type）产出错误分布；若用户问题含'现在可用吗'，历史日志只回答成因，再用一条明确标注的最小实测探针收口

## Stop conditions
- 已读到一条完整代表记录，聚合脚本一次跑通且与抽样核对一致
- 用户事实问题已被溯源一致的证据回答（含必要时探针回执），停止继续提取

## Verification
- 聚合总数与独立子集对账（如 73 settled + 8 unsettled 与派发总数一致，8 条错误各自可回查到 call_id）
- 结论引用的字段名/取值来自第 2 步 dump 的真实 schema，而非猜测词表；探针结论附带回执（如 run completed、final_answer、exchange_committed）

## Counterexamples
- 日志是无结构自由文本（无 JSON 记录）：dump 单条无意义，应改用 grep/检索
- 单条记录体量巨大（载荷含整页正文/MB 级内容）：打印键骨架（字段名+截断样例）而非完整记录
- 本会话早前已完整读过同类记录、schema 已确立：无需重复 dump
- 过滤词表已从可见数据无歧义确定且只需一次简单过滤：先 dump 属于多余开销
- 本方法只管提取机制；选择检验哪个假设、如何分层归因属根因分析范畴，不要用它替代假设设计
