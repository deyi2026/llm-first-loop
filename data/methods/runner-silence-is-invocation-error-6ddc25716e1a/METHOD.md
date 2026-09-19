---
method_id: runner-silence-is-invocation-error-6ddc25716e1a
name: runner-silence-is-invocation-error
description: 本 episode 最早摩擦：pytest 批次返回『退出码 0 + 0 行输出』（合法运行必有摘要行，这本身即异常），模型未诊断而是原样重跑、再用凭记忆的文件名（不存在的 test_history_elastic_budget.py）反复重组更大批次，多轮后靠 exit=4 才发现路径不存在。当时已有两条判别事实：摘要行缺失即调用层失败；ls 列出的目录清单已证明真实文件集。方法：凡终态必有摘要行的 runner，沉默=失败信号；批次含未验证的记忆路径时，先用目录真值校验路径再重跑，绝不把沉默当绿灯。
status: candidate
source_model: glm/glm-5.3
teacher_refs: method:method-self-distill-root-cause,method:method-self-distill-repo-api,method:method-self-distill-ab
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-09T18:58:07.600033+00:00
updated_at: 2026-09-09T18:58:07.600033+00:00
---
name: runner-silence-is-invocation-error
status: candidate
trigger:
  - 测试/构建类 runner（正常终态必有摘要行，如 pytest 的 'N passed'）返回 0 行输出，或 'no tests ran' 且退出码为 usage error（pytest exit=4）
  - 批量命令中的文件/路径名来自记忆，未在当前会话中列目录确认过
discriminator:
  - 合法 pytest 运行必输出摘要行且 collected>0；『退出码 0 + 0 行输出』不可能是真通过，这一异常本身就是诊断信号
  - exit=4（usage error，通常是路径不存在）≠ exit=5（路径存在但收集 0 用例）
  - 目录 ls/glob 列表是路径存在性的最低成本权威真值源
short_path:
  - 跑完先找摘要行：有 'N passed' 且 collected 数符合预期才算绿
  - 缺摘要/0 行/exit=4：不重跑同批命令，逐字核对该命令中每个路径（ls、glob 展开或按符号 grep 定位真实测试位置）
  - 用被证明存在的文件名（或目录 glob）重组批次重跑，确认 collected 数符合预期
  - 若长管道 tail 截断吞掉错误详情，去掉管道或改 tee 取完整输出
branch_on_evidence:
  - observation: 摘要行存在且计数符合预期
    next: 记录结果，停止该批次
  - observation: 0 行输出或 exit=4
    next: 判定为调用层失败，校验路径而非重试
  - observation: exit=5 且路径确实存在
    next: 查收集条件/标记，而非路径
stop_conditions:
  - 命令中被引用的每个路径都被证明存在，且 runner 摘要行显示预期数量的测试通过
verification:
  - 将命令中每个路径与目录列表逐一比对；或 pytest --co 确认无 'file or directory not found'
anti_patterns:
  - 把空输出/无摘要当作成功或无关紧要，继续扩大或重组批次
  - 用记忆中的文件名反复重跑而不与当前目录核对
  - 用 | tail 截断后丢失 usage error 详情，再基于残缺输出下结论
counterexamples:
  - grep/ls 等空输出具有合法语义的命令（『无匹配』是数据不是故障），不适用本方法
  - 测试模块本来就允许为空且 exit=5 是既定契约时，路径校验无益
  - 摘要行已在别处流式可见、回执 0 行只是传输问题时，应查传输而非路径
programizable:
  - 运行前对命令中每个路径做存在性断言（glob 展开/ls diff）；运行后断言输出匹配 passed|failed|error 且 collected>0
model_owned:
  - 判断 collected 数是否符合预期、候选路径名与任务意图的语义对应关系
why_shorter: 把『反复重组批次猜文件名』缩成『一次目录比对+一次重跑』，同时阻止把调用错误误读为绿灯造成虚假可信度。
