---
method_id: eval-store-isolation-at-binding-point-with-write-canary-08a376c4a22f
name: eval-store-isolation-at-binding-point-with-write-canary
description: 评测/跑批 harness 只靠临时 data_dir 声称隔离，而持久 store 由 env 覆盖链（METHODS_DIR/EXPERIENCES_DIR→resolver→factory 注入）实际绑定时，隔离必须在解析端点强制并用写侧 canary 验证：先用已有旁证（生产 usage/watermark 被跑批改写）确认泄漏真实存在；再加 store 模式开关（snapshot/empty/production，默认 snapshot、冷拷贝+逐样本分叉、构造期 fail-closed、最敏感组合硬拒）；最后用秒级干跑+生产树 git status 零改动证明不写回，report 记 digest 保跨 run 可比；并在烧真实调用预算前预校验报告期必需的 scenario schema 键。
aliases: 跑批别写穿生产库, data_dir 临时目录挡不住 env 覆盖, 评测隔离用 git status 干跑验证, 跑批前先钉死知识库绑定, held-out 跑批隔离检查, 评测快照隔离知识库
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:c5f52ba4-0dd0-440d-ab8e-d4b02bb2ed41:709:d0574b33bc4079ce192e
evidence_refs: learning:learn:bea1aa93ed42
created_at: 2026-10-25T15:28:38.685601+08:00
updated_at: 2026-10-25T15:28:38.685601+08:00
---
## Trigger
准备让评测/benchmark harness 跑真实（或高价）批前，harness 只传了临时 data_dir，但目标系统持久 store 的路径由独立解析链（env 覆盖键→resolver→装配注入 Settings）决定，隔离从未在绑定端点被验证过

## Discriminator
装配源码里 Settings 的 store 目录来自 resolved_paths 注入（config.py 把 experiences_dir/methods_dir 绑到解析结果），而 harness 直接构造 Settings 只传 data_dir → dataclass 默认值+factory 注入的生产 env 路径接管绑定；若生产树的 usage/watermark 文件 mtime/内容已被历史跑批改写，泄漏已被现成物证证实，无需再枚举怀疑面

## Short path
- 第一未知量：store 目录的绑定权威是谁——沿 装配点→resolver→显式 env 覆盖 的链一次查清，确认 harness 的 data_dir 是否根本不在这条链上
- 用已存在的旁证（生产 usage.jsonl/.usage_watermark.json 被跑批改写）把『可能泄漏』升级为『已证实泄漏』，再动手改代码
- 加显式 store 模式开关 {snapshot,empty,production}，默认非 production：批首冷拷贝生产库、每样本分叉副本、构造期 _assert_isolated fail-closed
- 最敏感组合（held-out 场景 + production 模式）构造期直接 RuntimeError，不留给操作者犯错空间
- 写侧 canary 收口：秒级干跑（含真实拷贝体积）后对生产树 git status，零改动即证明不写回；report.json 记录 store mode/来源/digest 作为 Δ指标可比前提
- 烧预算前的报告期预校验：render/report 阶段必需的 scenario 键（version/name 等）缺失应在启动秒级失败，而不是 138 次真实调用之后才 KeyError

## Stop conditions
- 干跑后生产树 git status 零改动，且 report 含完整 store 模式/digest 块
- held-out + production 组合被硬拒绝并有明确报错文案
- 模式矩阵定向测试全过：绑定/empty/snapshot/production/fail-closed/默认值/硬拒

## Verification
- snapshot 干跑（真实文件数/字节量）→ 生产树 git status 零 diff；对照旧行为必改写 usage.jsonl
- report.json 存在 knowledge_store 块（mode/isolated/来源/文件数/字节/digest）
- 定向测试覆盖每个模式 + fail-closed 断言 + 默认值 + held-out 硬拒
- 静态诊断（lint/类型 ratchet）对修改文件零新增

## Counterexamples
- store 无 env/resolver 覆盖链、data_dir 即唯一绑定权威 → 临时目录已真隔离，加模式开关是无谓复杂度
- 纯只读分析脚本从不写库 → 快照/分叉机制是纯开销，只需确认读侧
- 评测目的就是测量生产库检索质量 → 默认 snapshot 会切断被测机制，production 必须允许显式选择（仍记 digest）
- CI/干净环境未设置这些 env 键 → 默认解析已落在临时根下，先查 env 再决定是否需要防护
