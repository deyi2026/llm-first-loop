---
method_id: derive-direct-run-from-wrapper-source-9d61b63a698c
name: derive-direct-run-from-wrapper-source
description: 当包装脚本（entry script）跑通但不显示所需指标时，不要盲 grep 日志、也不要裸调底层命令；从已读过的包装脚本源码导出直调姿势：复刻其环境注入（如从 env 文件 grep key）并只改输出可见性标志。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-09T17:38:58.037555+00:00
updated_at: 2026-09-09T17:38:58.037555+00:00
---
name: derive-direct-run-from-wrapper-source
status: candidate
trigger:
  - 包装脚本/入口命令执行成功，但所需的具体指标或 print 输出未出现在其日志中（quiet 模式捕获了 stdout）
  - 需要绕过包装层直接调用底层测试/命令来取数
discriminator:
  - 包装脚本源码已经读过，其中明确包含：(a) 环境/密钥注入方式（如从 env 文件按 KEY= 行提取）；(b) 底层命令及其 verbosity/capture 标志
  - 若不复刻 (a)，底层命令会因缺密钥被 skip；若不知道 (b)，就不知道指标为何不可见
short_path:
  - 包装脚本跑完但日志无指标 → 回查已读的脚本源码：它注入哪些 env、用什么标志跑底层命令
  - 由源码组合直调命令 = 包装层的环境注入 + 底层命令 + 打开输出（-s/去捕获）；跳过对从未写入的日志做 grep
  - 首次直调不加窄过滤（或只 tail），先确认输出形态和 skip/失败原因；确认后再加过滤
  - 对每个目标/provider 重复同一导出姿势；相互独立的运行可并行
  - 拿到指标并对照阈值/历史记录核实后停止
branch_on_evidence:
  - observation: 日志/既有工件已包含所需指标
    next: 直接采集，不重跑
  - observation: 包装层暴露 verbose 开关且重跑成本低
    next: 带 verbose 重跑包装层，优先于推导直调
  - observation: 包装脚本源码未读过
    next: 先读源码再推导直调，而不是试错式裸跑
stop_conditions:
  - 所需指标已从一次环境契约与包装层一致的运行中取得，且非 skip、退出码正常
verification:
  - 输出行格式与预期指标形态匹配（含目标标识与数值）
  - 与文档/历史记录的数值可对照时不矛盾
anti_patterns:
  - 对 quiet 模式从未写入的日志反复 grep 指标
  - 首次运行陌生命令就用窄 grep 管道，吞掉 skip 原因后误判为空
  - 不移植包装层的 env 前置条件就裸调底层命令
counterexamples:
  - 日志或 CI 工件本来就有该指标 → grep 日志是正确且更便宜的做法
  - 底层命令无需任何 env 注入 → 直跑即可，无需读包装源码
  - 直跑成本高（付费 API、长回归）且存在报告工件 → 优先采集工件而非重跑
programizable:
  - 从包装脚本源码机械提取 env 注入行（KEY= grep/cut/sed 模式）与底层命令模板
  - 将『grep 无匹配导致管道退出码 1』识别为过滤先于输出形态知识的信号
model_owned:
  - 判断所需指标语义上是否由底层测试产生、重跑成本是否值得、输出何时已足够
why_shorter: 用已读脚本内的环境与输出契约，把『盲 grep 日志 + 缺 key 试错』压成一次可直接成功的直调。
