---
method_id: timeout-symptom-read-new-scanning-code-first-0a5d95cd9ddd
name: timeout-symptom-read-new-scanning-code-first
description: 当测试表现为挂死/超时（无断言失败），且近期 diff 新增了正则/扫描/解析类代码时，按性能回归处理：先读新增 pattern 找超线性结构，用带每阶段硬超时的对抗输入族微基准定位，修复后对同族输入验证再跑套件——而不是先枚举测试环境假设。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-09T20:30:28.952299+00:00
updated_at: 2026-09-09T20:30:28.952299+00:00
---
trigger:
- 测试超时/挂死（无断言失败输出），且首次挂起的 commit 新增了正则/文本扫描/解析代码
discriminator:
- 失败是 timeout 而非 assertion error → 性能问题而非逻辑问题
- 挂起起点与引入扫描代码的 commit 精确重合（git show --stat 即可确认新增模块）
- 新 pattern 存在嵌套量词结构（(?:X+)+ 型）且经 finditer 扫描可能无分隔的长文本
short_path:
- 症状分类：timeout → 性能回归方向，不做逻辑调试
- git show 挂起 commit 的 --stat → 直读新增扫描模块的 pattern 定义
- 发现嵌套量词 → 构造对抗输入族（无分隔长串、交替分隔符、超长同类字符）逐正则微基准
- 微基准每阶段必须带硬超时（SIGALRM/子进程 timeout），防止诊断脚本被同一 bug 挂死
- 修复一次到位（头窗口硬界 + atomic group 锁回溯），先对同一对抗输入族复测 + 正常输入语义抽查，再跑 pytest
- 附宽松时间上界防回归用例（挂死与正常差多个数量级，取宽界防 CI 抖动）
branch_on_evidence:
- observation: 相同输入在 harness 外也挂
  next: 确认代码超线性，继续对抗微基准
- observation: 裸跑通过但与 harness 输入不同
  next: 先控制输入一致再对比；裸跑通过不代表环境问题（本例输入长度差异才是真变量）
- observation: 相同输入裸跑通过、仅 harness 下挂
  next: 才转向 conftest/plugin/版本等环境分支
- observation: 失败是断言错误而非超时
  next: 按逻辑 bug 处理
stop_conditions:
- 对抗输入族全部线性（毫秒级）、正常语义抽查不变、目标测试与门禁通过
verification:
- 修复后用与定位时相同的对抗输入族复测；不信任在挂死污染下产生的历史 exit=0 证据，须重验
anti_patterns:
- 未读新增扫描代码前先枚举环境假设（conftest/pytest 版本/plugin autoload/stash 基线）
- 微基准不加每阶段超时，诊断本身被目标 bug 挂死后才补
- 修复只对单一输入形状验证就跑全套件；只加 possessive 不加窗口界/atomic 的半吊子修复
- 信任被挂死污染的旧"通过"证据
counterexamples:
- 失败为断言错误：性能定位无意义
- 相同输入在 harness 外正常、纯 harness 差异（fixture 死锁/输出捕获阻塞）：环境分支才是对的
- 正则无可回溯结构且输入有界：超线性不可能，查 I/O/锁/等待
programizable:
- 症状分类（timeout vs assertion）、git show --stat 关联新增文件、每阶段硬超时包裹的逐正则计时
model_owned:
- 识别 pattern 的回溯风险结构、设计对抗输入族、判断修复的语义损失是否可接受
why_shorter: 用"timeout+新增扫描代码"两条当时已知事实把根因缩到新模块 pattern 结构，跳过环境枚举；每阶段超时保证诊断与修复验证各只需一轮。
