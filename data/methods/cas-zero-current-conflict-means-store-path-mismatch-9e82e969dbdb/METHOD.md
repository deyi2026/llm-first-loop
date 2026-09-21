---
method_id: cas-zero-current-conflict-means-store-path-mismatch-9e82e969dbdb
name: cas-zero-current-conflict-means-store-path-mismatch
description: 当 CAS/世代冲突错误报告 current=0（空 store 哨兵）而独立权威状态显示记录仍在期望世代时，首要假设应是'失败工具解析到了另一个空 store 路径'，而非并发写入。对比权威状态 + 读该工具 main()/argparse 源码，确认 store 路径由哪个输入决定（显式 flag > 默认值；环境变量是否被读），再按推导规则直接验证真实 store 文件。路径由显式入参决定时不要按文件名全库枚举——会捞出审计快照、worktree 副本等陈旧同名文件。CAS 在写入前被拒即无状态损坏，报告根因与正确调用方式后停止。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16fe103b-bd92-4cdd-984a-f6cd5b45235c:821:fc89815c0a22350f1973
evidence_refs: learning:learn:3bb16612e215
created_at: 2026-09-20T17:11:59.650919+00:00
updated_at: 2026-09-20T17:11:59.650919+00:00
---
## Trigger
乐观并发/CAS 世代冲突报错显示 current=0 或空哨兵值，且另有独立权威状态源显示同一记录仍存在于期望世代、进程仍绑定该世代

## Discriminator
冲突方 current=0（store 不存在哨兵）与权威状态'记录活着且为期望世代'在最初就同时可见；两者矛盾直接排除'真被并发改写'，把未知量缩为'冲突工具把 store 解析到哪、由哪个输入决定'；traceback 同帧已给出 raise 的文件与行号，可一步读到路径推导逻辑

## Short path
- 读 traceback：current 是 0/空哨兵而非另一个世代数 ⇒ 首要假设为 store 路径不匹配，而非竞态
- 与一次权威状态查询对比：记录存在于期望世代 ⇒ 路径不匹配假设成立；且 CAS 在写前被拒 ⇒ 断言无状态损坏
- 读该 CLI 的 main()/argparse 源码，确认 store 路径由哪个输入决定（显式 flag、默认值、环境变量是否被读），不凭文档或习惯假设
- 按推导规则直接读取真实 store 文件（如 <runtime_root>/data/runtime/<store>.json），验证世代/记录 ID 与权威状态一致
- 报告根因（错误的 data-dir / 被忽略的环境变量）与正确调用方式；提示失败调用在错误目录留下的空 runtime/ 锁文件可清理；停止，不据此直接变更 desired state

## Stop conditions
- 真实 store 文件已在推导路径上验证，世代/记录 ID 与权威状态一致
- 入参解析规则已从 main()/argparse 源码逐行确认，并已给出正确调用方式
- 若后续要重发写操作，须另持完整门禁回执；本方法只覆盖诊断，不覆盖发布决策

## Verification
- 真实 store 文件内容（世代、记录 ID）与独立权威状态输出一致
- 冲突 CLI 的路径解析规则来自源码确认，而非假设环境变量生效
- 确认 raise 发生在任何写入之前（对照源码 CAS 逻辑），从而断言无状态损坏

## Counterexamples
- current 为非零且不等于期望值：这是真实并发发布/竞态，路径不匹配假设不适用，应追查谁发布了该世代
- 工具本就按 workspace/tenant 使用独立空 store：current=0 是首次发布正常态，不应'修复'为指向别的 store
- schema 中哨兵 0 与合法世代 0 不可区分：必须先做 store 文件级检查再下结论
- 无独立权威状态源可用：不能仅凭 current=0 断定路径错，需先让工具暴露其解析出的实际路径
- store 路径并非由显式入参推导（依赖 cwd/环境/发现机制）：按名枚举或发现式搜索才是合理手段
