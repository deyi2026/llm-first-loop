---
method_id: resolve-live-data-path-from-reader-code-not-filename-enumeration-d2c7eee59184
name: resolve-live-data-path-from-reader-code-not-filename-enumeration
description: 定位运行时数据工件（审计 jsonl、样本池、记录库）时，若内容搜索命中已暴露读取方代码的路径构造（如 search.py:538 的 self._audit_dir / "declaration_check.jsonl"），未知量已收缩为『该目录参数在当前部署的具体值』。应通过 factory/config/env 或已知可用的 sibling 文件（self_eval_log.jsonl→data/audit）解析这一个参数，而不是按文件名全树枚举：venv、evals 快照、data_ab 实验目录中的同名拷贝意味着文件名相同≠活实例，活实例由运行配置定义。本集在路径模板已知后仍做了 honesty 内容搜索、evals 文件名搜索、.lfldata 猜测 ls、21 命中的全库 find、env dump 共约 5 步扩散才落到 data/audit/，且 find 的首个可见命中全是实验拷贝，误读即得错误样本池。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:d8f59859-1341-4560-9f92-9163e49963d5:22:ad7b6c3162f98d7dc216
evidence_refs: learning:learn:8bf43c5514af
created_at: 2026-09-30T08:13:48.032485+08:00
updated_at: 2026-09-30T08:13:48.032485+08:00
---
## Trigger
需要定位并读取某个由运行时系统写入/读取的数据工件（审计日志、自评样本池、记录库），但尚不知道其确切磁盘路径。

## Discriminator
读取方代码的路径构造表达式已在内容搜索命中中可见（<dir_param> / "<filename>"），说明路径模板已知、唯一未知量是目录参数的部署值；同时磁盘上存在多个同名文件（evals/ 结果快照、data_ab/ 实验拷贝），证明按文件名枚举产生的是无法区分权威性的同义候选。

## Short path
- 读消费该数据的代码（aggregator/reader，如 _read_declaration_checks、search.py 的 path= 行），取得 <dir_param> / "<file>" 路径模板。
- 解析 dir_param 的具体值：读构造该 reader 的 factory/config 一跳；或利用已验证可用的查询入口（search_records 正常返回即证明 audit_dir 存在且被索引）+ 顶层 data 目录/已知 sibling（self_eval_log.jsonl 在 data/audit/）钉死为 data/audit。
- 只对这一个具体路径执行统计与读取（wc -l、consistent 计数、窗口过滤），得到 3065 行 / 742 False。
- 校验文件 keys 与代码 schema 字段一致、窗口统计能复算聚合器指标（41 条窗口内、rate≈0.878），停止发现。

## Stop conditions
- 已从与 reader 代码路径构造逐段一致的文件取得目标样本/记录，且字段 schema 与代码定义吻合。
- dir_param 无法由 config/env/sibling 唯一解析（存在多个部署根）——此时才允许列出同名候选，并按运行配置 provenance 消歧。

## Verification
- 最终读取路径与代码中路径构造表达式逐段一致（audit_dir 解析值 + declaration_check.jsonl）。
- 样本统计（总行数、True/False 分布、keys）能复算 SelfEvaluator 报告的窗口指标，口径（span=50、window_hours=24、先时间过滤）一致。
- 明确确认未把 evals/*/results 或 data_ab/* 下的同名拷贝当作样本来源。

## Counterexamples
- 仓库内没有任何读取该数据格式的代码（外部工具产出的二进制/专有格式）→ 无路径构造可循，文件名/内容全盘搜索才是正确起点。
- 任务本身就是盘点某文件的全部副本与差异（如实验工件审计、迁移清点）→ 全树 find 是目标动作，本方法不适用。
- 代码中的 dir_param 对应多个候选部署根且 config/env 未定 → 需先做一次显式消歧（此时枚举+provenance 排序合法），消歧后才收敛到单文件。
