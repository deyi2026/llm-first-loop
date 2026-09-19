---
method_id: preflight-literal-contracts-before-expensive-runs-d8b4cd348efa
name: preflight-literal-contracts-before-expensive-runs
description: 启动耗时门禁/包装脚本整跑前，静态枚举并批量校验 consumer 对 producer 的全部字面量契约（进度标记、清单哈希、临时文件模板），把『每轮整跑串行发现一个失配』压成启动前一次秒级预检。
status: candidate
source_model: glm/glm-5.3
teacher_refs: method:method-self-distill-root-cause,method:method-self-distill-repo-api,method:method-self-distill-ab
source_episode_refs: session:2274a444-654d-46a3-a72b-2d83058b2289
created_at: 2026-09-09T20:47:28.826762+00:00
updated_at: 2026-09-09T20:47:28.826762+00:00
---
trigger:
  - 即将启动一次分钟级的门禁/包装脚本整跑（consumer wrapper 消费另一组件 producer 的输出）
  - consumer 通过字面量断言 producer 行为：进度/步进标记串、fixture 清单哈希、临时文件模板、路径
  - producer/工件/运行环境自上次绿灯后有变更（典型：外部演进链只改 producer 一半，未同步 consumer）
discriminator:
  - grep consumer 中所有被断言的字面量，逐项与 producer 当前源码/工件静态比对；任一失配在零成本时点即可确认，无需整跑暴露
short_path:
  1. 启动整跑前，枚举 consumer 对 producer/环境断言的全部字面量（标记串、manifest 哈希、mktemp 类模板）
  2. 逐项静态验证：标记串存在于 producer 当前输出格式串中；哈希与当前工件重算值一致；模板满足沙盒约束
  3. 所有失配一次性批量修完（对准当前格式/同步新哈希），再启动整跑
  4. 若仍失败，先归类为『未枚举到的新契约类』或真实测试红，补充枚举或走红集归因，禁止只修表象即重跑
branch_on_evidence:
  - observation: 某字面量在 producer 当前源中不存在或格式已升级
    next: 判定契约漂移，修 consumer 对准当前格式（不回滚 producer）
  - observation: 工件哈希与 manifest 不一致
    next: 确认工件变更来源后同步 manifest 新值，不把工件修回旧值
  - observation: 枚举字面量全部通过而整跑仍失败
    next: 属新契约类或真实红，进入红集精确收集与归因分流
stop_conditions:
  - 枚举的字面量契约全部静态验证通过，且一次整跑绿灯
  - 或整跑失败但已归类为非契约类（真实测试红/环境问题）
verification:
  - consumer 探测标记能在 producer 源码输出格式串中 grep 到
  - manifest 哈希等于对当前工件的重算值
  - 读门禁日志用二进制安全方式（grep -a / tail -c）：输出常含 emoji/ANSI 字节，避免把 UnicodeDecodeError 误当门禁失败
anti_patterns:
  - 只修上一轮整跑暴露的那一个失败类就立即重跑，串行烧多轮分钟级整跑
  - 探针断言旧格式而 producer 已被外部链升级，靠整跑才发现标记永不匹配
  - 把哈希漂移『修复』为回滚工件
  - 对已证明不含目标内容的检索源反复换关键词重查，而非切换 provenance 来源
counterexamples:
  - 门禁整跑只需数秒：预检成本高于直接执行，直接跑
  - 标记由运行时动态计算（步数/路径推导）：静态 grep 字面量不适用，需按 producer 同算法推导或采样一次真实输出
  - consumer 只消费退出码、无字面量断言：无契约可预检，跳过
  - consumer 与 producer 原子同版本变更且 CI 强制共变：失配风险极低，预检可省
programizable:
  - 提取 consumer 被断言字面量并自动 grep producer 源/重算工件哈希的静态比对器
model_owned:
  - 判断哪些字面量与本次目标语义相关、失败归类（契约漂移 vs 真实红 vs 新类）、何时证据已足够停止预检
why_shorter: 把『每轮整跑发现一个失配』的串行分钟级发现，压成启动前一次秒级静态批量校验。
