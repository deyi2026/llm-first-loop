---
method_id: verify-causal-chain-before-kb-enumeration-30c124a06330
name: verify-causal-chain-before-kb-enumeration
description: 验证一条关于运行时行为的根因假设时，若初始符号检索已点名完整调用链的 file:line，先沿这条链逐文件闭环证据，再去做知识库/记录的宽泛检索（后者只服务于改法设计，不服务诊断）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:2274a444-654d-46a3-a72b-2d83058b2289
created_at: 2026-09-09T18:30:50.964827+00:00
updated_at: 2026-09-09T18:30:50.964827+00:00
---
trigger:
  - 需要验证"某机制在运行时阻塞/拖慢了某个用户可见信号"这类根因假设
  - 初始符号级 grep 已返回关键符号的 file:line 分布
discriminator:
  - 初始 grep 输出是否已同时点名三类位置：可疑后处理 hook 的调用点、其实现文件、被影响信号（完成事件/忙判定/锁租约）的处理点。三类都已出现时，候选文件已从全仓库缩到约 4~5 个，无需再全库枚举
short_path:
  1. 保留初始符号 grep，得到链条 file:line 图；未知量：信号由谁产出、产出前还同步执行什么
  2. 按 grep 行号只读 hook 调用点附近代码；未知量：可疑后处理是否同步发生在结果返回/信号发出之前
  3. 读 grep 点名的实现文件；未知量：外部调用次数、超时、触发条件
  4. 读信号发出点与锁/租约释放点；未知量：哪些用户可见信号被排在该同步工作之后
  5. 查部署配置确认开关与超时实值；未知量：该机制在本环境是否启用
  6. 链上每环均有 file:line 证据后才查 docs/records，为改法取约定与可复用模式
branch_on_evidence:
  - observation: grep 已给出完整链条点名
    next: 按链序逐文件读，暂缓知识库宽查询
  - observation: 某一环在代码中缺失或与假设矛盾
    next: 记录反证并报告假设不成立，而非继续枚举其他可能
  - observation: 诊断链已闭环
    next: 停止诊断；知识库检索仅服务于方案设计
stop_conditions:
  - 触发条件、同步调用点、被阻塞信号、部署配置四环均有 file:line/配置行证据
verification:
  - 最终答复中每条根因结论都能指回一个已读过的代码/配置位置，未读文件不进入证据链
anti_patterns:
  - 拿到链条点名后先并行发 docs/records/evidence 的宽泛关键词查询
  - 对同一文件的重叠行段重复 read
  - grep 报"文件不存在"后换路径继续猜，而不是立即定位真实模块位置
programizable:
  - 从符号 grep 结果抽取 file:line 并按生产者→消费者排序生成待读清单；检测同文件重叠行段重复读；检测在读取任何链上文件之前发出的知识库宽查询
model_owned:
  - 判断哪些 grep 命中与用户症状语义相关、链条何时算闭环、反证是否足以推翻假设
why_shorter: 用已到手的链条点名把"全仓库扫描+三库检索"缩成沿 4~5 个命名文件的顺序读取，砍掉先验枚举分支。
counterexamples:
  - 假设对象是设计沿革/历史决策而非运行时行为 → records/docs 检索是主证据，此法不适用
  - 初始 grep 无命中或只命中测试代码 → 宽发现（目录/文档层）才是正确下一步
  - 症状是生产环境时延等行为问题 → 日志/指标优先，调用点顺序只能提供假设
  - 符号在多个子系统重名、链条不清晰 → 允许一次定向 scope 查询后再深读
