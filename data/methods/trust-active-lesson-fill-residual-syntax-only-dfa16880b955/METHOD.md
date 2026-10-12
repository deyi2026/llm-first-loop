---
method_id: trust-active-lesson-fill-residual-syntax-only-dfa16880b955
name: trust-active-lesson-fill-residual-syntax-only
description: 当某操作已有 status=active 且带证据的经验记录完整覆盖时——既声明权限边界又给出端到端合规流程——直接按记录执行：模型侧完成前置检查与构建，operator-only 步骤作为一条精确命令交接，残余未知（如 CLI 确切参数）只做一次定点查证。不要从源码重新推导记录已回答的机制（guard 挂载点、拦截通道）。本例经验已写明 publish/worker 为 operator-only 及 ff→build→publish+verify→唯一一次 restart-all 的流程，后续 6 次脚本目录枚举与 guard 接线考古属于对已记录事实的重复推导。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:433:d80987a05b27e3a179f2
evidence_refs: learning:learn:821dfa20e9fe
created_at: 2026-09-19T02:09:34.938018+00:00
updated_at: 2026-09-19T02:09:34.938018+00:00
---
## Trigger
任务需在某子系统执行变更/部署流程，且已检索到匹配当前场景的 active 经验记录（record_kind=lesson，带 evidence 指针），其正文同时声明了权限边界（哪些子命令 operator-only）与完整合规流程；此时若下一步的冲动是'先弄清机制如何工作'，应先检查记录是否已回答'该怎么做'。

## Discriminator
摩擦发生前，经验记录正文已同时给出两条可判别事实：(1) 权限边界——'CLI publish/worker 又是 operator-only，模型会话无法自行改 desired'；(2) 流程——先在正仓 fast-forward → 重建 webui 产物 → 从正仓根以 expected-generation=当前代际 publish 并 verify → 确认后仅发一次 restart-all。这两条把'如何更新 desired 并重启服务'从宽空间（脚本入口？guard 挂哪？能否绕过？）缩为一个固定分工：模型做 ff/build/preflight/verify，operator 执行 publish，模型发一次 restart。

## Short path
- 取决策所依赖的权威状态事实：两个 PR 的合并态、desired 与 live 的 generation/git_head 差异（确认与经验记录的适用前提同型）
- 读取匹配的 active 经验记录，提取三要素：权限边界、合规流程、已知失败模式；把后续每个未知量对照这三要素分类
- 只对记录未覆盖的残余未知做一次定点查证：grep 目标 CLI 子命令的 argparse 定义，拿到 operator 交接命令的确切 flag（如 expected-generation/code-root/runtime-root）
- 执行模型侧前置：untracked 与新增 tracked 路径重叠检查（重叠文件字节级比对）、ff、重建产物、用 worker 同款命令预跑 preflight、只读 verify 确认仅剩预期差异
- 把 operator-only 步骤作为一条含确切参数的命令交接给用户并停止；待用户确认后再发唯一一次 restart，并做 manifest→进程→端点三层验证

## Stop conditions
- 经验流程已执行到权限边界，交接命令包含全部确切参数（子命令、flag、expected-generation），且明确声明不尝试绕过
- 只读 verify 的残余差异与经验记录预测完全一致（仅 desired vs actual 的 git_head/代际差），无新增异常项

## Verification
- 交接命令的每个 flag 与 CLI parser 的实际定义逐项一致（这是唯一必要的源码定点核对，一次 grep 即可）
- 应用经验前核对当前事实与其适用前提同型：同样的 mismatch 模式、同样的 code_root 场景、记录 status 仍为 active

## Counterexamples
- 经验的 evidence 时间戳早于该子系统的大重构（guard/CLI 语义可能已变）——此时机制核验优先于直接套用流程
- 用户的任务目标就是机制本身（如'guard 挂在哪条通道、如何判定'）——源码考古是任务本体而非开销，本方法不适用
- 当前场景与经验在关键前提上不同（如本就从正仓操作、无 divergence，或 desired 代际语义已改）——只能套用仍相关的部分，其余需重新验证
- 不存在匹配的 active 经验记录——宽发现（目录/调用图/全仓 grep）才是正确起点，本方法无触发条件
