---
method_id: runtime-activation-verify-artifact-and-import-resolution-e80b42b787ec
name: runtime-activation-verify-artifact-and-import-resolution
description: 验证'改配置/代码并重启后，功能是否真在运行时生效'时，优先用两个直接可观测量：(1) 该功能独有的运行时产物（journal/队列/状态文件）的存在性 + mtime 对比重启时刻；(2) 用服务自己的解释器跑一条 import 探针（python -c 'import pkg; print(pkg.__file__)'）解析实际生效的代码根。日志中缺少预期行不构成否定证据（可能是级别/过滤/轮转）。只有两者都不可得时，才回退到 ps/lsof/cwd/.env/脚本头的进程考古。两个观测量各自闭合一个未知量：产物=是否激活，import=哪份代码默认在生效。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:177:7f99a3ffe4c2e3fd9ec9
evidence_refs: learning:learn:1d9c03ca38eb
created_at: 2026-09-17T15:00:29.624991+00:00
updated_at: 2026-09-17T15:00:29.624991+00:00
---
## Trigger
服务重启或配置/代码变更后，需要确认某个开关型功能在运行中的服务里真的激活；典型诱因是预期日志行缺失，引发'功能没生效'的怀疑。

## Discriminator
当时已知的两条事实：(a) 该功能存在只有它才会写的专属产物路径（本例 data/sessions/learning/journal.jsonl，自己上一轮实现时已知路径）——存在且 mtime>重启时间戳即是激活的直接见证；(b) 服务所用 venv 解释器可本地调用（重启脚本里 VENV_PY=.venv/bin/python 已可见），一条 import 探针即解析生效代码根。相比之下'日志缺一行'不缩小任何假设空间（级别/过滤均可解释）。

## Short path
- 重启回执 rc=0 后定义未知量：功能 X 是否在运行服务中激活（回执只证明服务活着，不证明功能生效）。
- stat 功能专属产物：存在且 mtime 晚于重启时间戳 → 直接见证激活，跳过进程考古。
- 用服务同一 venv 执行 python -c 'import llm_loop; print(llm_loop.__file__)'：一次调用回答'我改的代码默认是否到达运行时'（主检出 vs deploy worktree）。
- grep .env 显式变量：环境覆盖旧代码默认 → 解释'旧代码默认 + 新开关仍激活'的组合。
- 读产物内容（事件生命周期）确认闭环行为正常；'激活'与'生效配置'两个未知量均有直接证据即停。

## Stop conditions
- 激活已由新鲜产物见证，且生效代码根与配置已被解释（代码根 + env 覆盖），停止枚举进程内部状态（ps/cwd/lsof/脚本头）。
- 产物缺失且同解释器 settings 解析显示开关为 off：以直接证据下'未激活'结论。
- 不再因'日志缺一行'追加新一轮进程/脚本排查。

## Verification
- 产物 mtime 严格晚于重启时间戳；仅看存在性可能是跨重启的陈旧残留。
- import 探针结果与重启实际使用的 code root/部署记录一致，而不是自己正在编辑的检出。
- 任何'未生效'结论不得仅凭日志缺行；需产物缺失或 settings 解析的独立佐证。

## Counterexamples
- 功能只打日志、不写任何专属产物文件 → 产物检查不可用，必须退回'日志 + logger 级别核验'。
- 产物跨重启持久存在且未清理 → 仅看存在性会误判激活，mtime 对比是必要条件。
- 被探针的解释器与服务真实解释器不一致（系统 python、容器、另一 venv）→ import 解析会误导，须先从进程确定真实解释器再探。
- 远端/容器化服务无法本地调用同解释器 → 方法降级，改用配置导出端点或健康检查自描述。
