---
method_id: gate-on-captured-exit-code-c32ebd89e7e8
name: gate-on-captured-exit-code
description: 当门禁命令的退出码已被刻意捕获进日志时，退出码+完成度标记即权威判定；统计行被插件吞掉不应触发多轮取证，精确计数只在验收确需时做一次机械推导。
status: candidate
source_model: glm/glm-5.3
teacher_refs: method:method-self-distill-root-cause,method:method-self-distill-repo-api,method:method-self-distill-ab
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-09T23:34:53.293724+00:00
updated_at: 2026-09-09T23:34:53.293724+00:00
---
trigger:
  - 后台/全量门禁命令结束时，日志里已有自己追加的 exit=$? 记录，但 pytest 风格的 'N passed' 统计行缺失或被插件输出（warnings/audit 块）截断
discriminator:
  - 测试类命令的退出码本身就是权威判定：exit=0 ⇔ 无失败无错误；配合进度标记到 100%、grep -c FAILED 为 0，门禁结论已充分。首个探测动作就已暴露这三项，继续换 pattern 找统计行不改变结论
short_path:
  - 运行门禁命令时始终把退出码追加进日志（同一 shell 内 echo exit=$?）
  - 结束后一次读取：退出码 + 进度尾部 + FAILED 计数
  - 三者一致为绿 → 立即判绿收口，不再追统计行
  - 仅当验收确需精确数量时，对日志内已有进度标记做一次确定性计数（如 awk 统计 progress dots），不换 flag 重跑 collect
branch_on_evidence:
  - observation: exit=0 且进度到 100% 且 0 FAILED
    next: 判绿并停止取证
  - observation: 统计行被吞但需要精确计数
    next: 一次机械解析已有日志，而非多次 grep 变体或重跑收集
  - observation: 退出码未被捕获或可能来自管道末端（cmd|tee）
    next: 退出码不作权威，须补真实统计行
stop_conditions:
  - 权威退出码为 0 且失败计数为 0，满足门禁判据即停止
verification:
  - 确认退出码属于目标命令本身（$? 未被管道/后台包装丢失），且日志对应完整结束的运行而非被 kill 的部分运行
anti_patterns:
  - 已有 exit=0 后仍反复用不同 pattern 找更漂亮的统计行（本例 ~8 次探测全落空）
  - 统计行被插件截断后换 flag 重复 collect-only，而收集输出被同一插件污染，注定失败
  - 结构化工具拒绝可选字段后，连续臆测第二种格式重试；一次失败后应省略可选字段或先查真实格式
counterexamples:
  - 验收明确要求'不少于 N 项测试被执行'以防收集被跳过：exit=0 不充分，须一次性点数
  - 退出码经管道丢失、或命令以 always-zero wrapper 包装：退出码非权威，必须看统计行/失败详情
  - 日志可能来自超时截断的运行：先确认运行完整结束再信退出码
programizable:
  - 统一日志尾部追加 exit=$?；收口解析器优先提取退出码与 FAILED 计数并输出充分性判定
model_owned:
  - 判断精确测试数是验收必需还是叙事修饰；判断进度标记与退出码是否语义一致
why_shorter: 把'找更好看的统计行'的多轮 grep/重跑探测压缩为'退出码即判定'的一次充分性检查，候选动作从任意取证变体缩为一个验证跳。
