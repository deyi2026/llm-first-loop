---
method_id: smoke-one-job-verify-capability-receipt-before-parallel-fan-out-5394d1c03bc4
name: smoke-one-job-verify-capability-receipt-before-parallel-fan-out
description: 当一批并行后台任务的整体价值依赖某个工具能力/参数，而本会话尚无任何回执证明它生效时，先发起 1 个最小冒烟任务并核验回执（exit=0、stderr 无插件/patch/provider 错误、参数被 echo 或落盘），通过后才 fan out 其余任务。本集把『dsh_task 有原生 reasoning_effort 参数』当作已验证事实，一次性发起 6 个 job 并盲等 120s，结果全部启动失败；更重的代价是实验核心自变量实际从未被操控，成为事后才发现的设计偏离。对工具能力的语言断言不等于回执证据；批量承诺应推迟到首个回执确认之后。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:45ef6204-2fe4-41a9-a21b-61f2a429d13a:230:8f1eff23bb58bfd5d1a6
evidence_refs: learning:learn:439885449de2
created_at: 2026-10-18T02:46:54.473892+08:00
updated_at: 2026-10-18T02:46:54.473892+08:00
---
## Trigger
准备一次性并行发起 N>1 个后台任务（实验组、批处理、子 agent 批量），且整批有效性依赖某个关键工具能力或参数，而当前会话没有任何回执（参数 echo/生成配置/patch/成功 exit）证明该能力生效；或仅凭口头断言（『它有原生 X 参数』）就宣布机制可用。

## Discriminator
看启动回执与会话内历史回执：若回执只含任务正文和 job_id、未 echo 关键参数，且同一工具链本会话已出现兼容/残留/patch 类摩擦（如清理时发现 8 个残留进程、旧 job 状态异常、CLI 需 patch hack 绕过截断），则『能力生效』仍是未验证断言——这一个观察即可把『直接 fan out』缩成『先冒烟 1 个再决定』。

## Short path
- 列出整批任务共同依赖的关键能力/参数，问：本会话有没有任何回执证明它生效？（未知量：机制可用性）
- 没有 → 只发起 1 个带同参数的最小任务，短间隔轮询其 job_output（未知量：exit code 与 stderr）
- exit!=0 或 stderr 含 plugin/peerDependencies/provider/patch 类错误 → 判定能力不可用，先修工具或改设计（如改为指令诱导），不发起其余 N-1 个
- exit=0 且参数在回执或落盘产物（命令行/配置/patch）中可见 → fan out 其余任务
- 在实验/任务记录中把『机制已验证（引回执）』与『机制仅断言或仅指令近似』分开标注

## Stop conditions
- 冒烟任务 exit=0 且回执/产物确认关键参数已生效 → 立即 fan out，不重复冒烟
- 冒烟失败或回执对关键参数沉默 → 停止批量，先修复机制或改设计，再用单任务重试
- 该能力在本会话已有带参数证据的成功回执，或该参数与批量结论无关 → 跳过冒烟直接执行

## Verification
- 首个任务 exit=0 且 stderr 无 plugin/peerDependencies/provider/patch 报错
- 回执或生成的配置/patch 文件中实际出现该参数名与值
- 若参数声称改变模型行为，另需行为侧差异证据（输出长度/耗时/风格）；回执 echo 不等于后端生效
- 最终结论中明确标注自变量是回执验证的还是仅指令近似（设计偏离如实入档）

## Counterexamples
- 任务彼此独立、廉价、失败可自动重试，且参数只是便利选项不影响结论 → 直接并行，冒烟只增加延迟
- 启动回执本身完整 echo 参数列表并确认生效 → 第一个任务即冒烟，无需额外串行步骤
- N=1 或本就顺序执行 → 无 fan-out 可保护，直接跑并读回执即可
- 同工具+同参数组合本会话已有多次带证据的成功回执 → 重复冒烟属于无信息重复动作
