---
method_id: no-identical-retry-on-deterministic-param-error-receipt-8c5c35a2bb26
name: no-identical-retry-on-deterministic-param-error-receipt
description: 当工具回执是确定性参数契约错误并逐字点名无效输入（如 'workdir 不是有效目录: /workspace'）时，该回执已是对该参数值的终局判定：世界未变、参数未变则结果必然复现，原样重发是零信息动作。正确路径是先做一次发现型动作（pwd/ls、或读取此前已自报 source_ref 的状态源）观测真实值，再以修正后的参数重发一次；修正后仍失败且错误文本变化才升级为环境/契约诊断。必须与瞬时失败（超时、连接重置、限流、模糊搜索空结果）严格区分：只有后者允许重试或改写措辞。本集两次逐字相同的 '/workspace 无效' 失败后，一次 pwd && ls 即解析出真实根目录 ~/Project/llm-first-loop-mirror。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e80a8cde-8a96-4b11-ad03-3f16341a32f5:1894:a1c80cc90c25e8163bbc
evidence_refs: learning:learn:4ab3c846803b
created_at: 2026-10-09T15:13:17.345295+08:00
updated_at: 2026-10-09T15:13:17.345295+08:00
---
## Trigger
工具返回点名式确定性参数错误回执（显式给出参数名与无效值，如 invalid directory / unknown key / bad path），且接下来准备再次发起同一调用。

## Discriminator
回执文本本身确定指认哪个参数的哪个值无效——本集 'workdir 不是有效目录: /workspace' 连续两次逐字相同。这是 404 型终局事实而非 transient，且两次调用之间无任何动作改变过文件系统状态，故同一调用的重发成功率为零；同时当时没有任何在案事实预知正确根路径，所以禁止的是重发、不是禁止首次尝试。

## Short path
- 收到点名式参数错误回执后停止重发；从错误文本提取参数名与无效值（未知量：真实有效值是什么）
- 执行一次最小发现动作（pwd && ls -d */ 或查询已自报自身 source_ref/endpoint 的状态源）取得真实根/路径
- 以修正后的参数重发原调用一次，成功回执即回到原任务流
- 若修正后仍失败且错误文本已变化，停止重试，转为环境/契约层面的诊断

## Stop conditions
- 修正后的调用成功返回
- 修正后仍失败但错误文本已变化——说明瓶颈已不是该参数值，继续重试无信息量

## Verification
- 修正后首次调用的回执为 success，且其返回内容与发现动作观测值一致（如 pwd 输出的根目录与后续 git/tool 操作同根）

## Counterexamples
- 瞬时/环境类失败（timeout、连接重置、限流、模糊搜索空命中）：回执未点名无效输入，重试或改写措辞是正当的，本方法不适用
- 两次尝试之间前提已改变（如已先创建目录/文件再重试同一路径）：参数未变但世界已变，重试合理
- 第二次调用面向语义可能不同的另一工具：复用同一路径是在检验新契约而非盲试；仅当回执文本逐字相同（同一契约同文报错）时本方法才适用
- 回执只说'失败'但不指认参数或原因的模糊错误：无终局判定可依，应先诊断而非套用本方法
