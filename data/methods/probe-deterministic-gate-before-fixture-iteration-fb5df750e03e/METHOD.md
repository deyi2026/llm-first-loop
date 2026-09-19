---
method_id: probe-deterministic-gate-before-fixture-iteration-fb5df750e03e
name: probe-deterministic-gate-before-fixture-iteration
description: 当阈值/预算门控分支在测试中未按预期触发时，先用最小探针直接对 fixture 内容求值门控函数、解出确切数值，再一次性写对测试；不要用反复改 fixture 字面量+跑全量测试来搜索答案。
status: candidate
source_model: glm/glm-5.3
teacher_refs: method:method-self-distill-root-cause,method:method-self-distill-repo-api,method:method-self-distill-ab
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-09T18:44:14.317801+00:00
updated_at: 2026-09-09T18:44:14.317801+00:00
---
trigger:
- 测试期望某个 threshold/budget 门控分支触发（或不触发），首轮运行显示未触发
- 门控是源码可读的确定性数值函数（预算、比率、消息尺寸、env 变量）
discriminator:
- 门控公式已被 grep/sed 读到 + 分支在当前 fixture 未触发 ⇒ 剩余未知量是一个数值交叉点，一次直接求值即可解出，无需在 fixture 空间枚举
- 若门控读 env，探针必须显式 pin/pop 该 env——环境遮蔽本身是未知量的一部分
short_path:
1. 跑一次测试，确认失败形态是“目标分支未触发”而非断言内容错误
2. 一次 grep/sed 读出门控公式，列出全部输入：阈值、比率、env、各消息尺寸
3. 写 5 行探针：用 fixture 的真实消息跨候选值调用该函数，打印哪些单元被归档/保留/走兜底
4. 从探针输出选 fixture 数值，一次写对测试；测试内 pin 住相关 env
5. 后续层间透传新开关时，以最近一个同类开关的接线为模板：第一次完整 grep 的结果就是完整接线图，不再换作用域重复 grep
branch_on_evidence:
- observation: 探针显示任何候选值都无法触发分支
  next: 改怀疑接线（flag 未传到函数），切换到沿 flag 路径追踪
- observation: 探针输出在值 X 处翻转
  next: fixture 取 X 与 X 邻值，断言两侧行为
stop_conditions:
- fixture 数值由探针导出，开/关两侧均有断言，定向测试+lint 绿
verification:
- 默认关闭侧仍复现旧行为（零回归用例）
- 探针的 env 假设与测试内 env pinning 一致
anti_patterns:
- 用整轮测试运行作为数值未知量的反馈回路，反复猜 fixture 字面量
- 第一次 grep 已返回完整接线图后仍换参数近似重复搜索
counterexamples:
- 未触发的根因是 flag 未透传：数值探针“通过”但分支仍死，必须改为追踪接线
- 门控含随机性/时间/外部状态：单次探针可误导，需播种或采样
- fixture 数值由规范强制指定（无自由度）：探针只用于理解，不改 fixture
programizable:
- 识别模式：≥1 次“期望标记缺失”型失败 + 门控函数对参数/env 纯确定 → 自动生成探针脚手架
model_owned:
- 判断未触发是数值问题、接线问题还是断言内容问题；判断探针证据何时足够
why_shorter: 把 k 轮猜值-跑测循环（每轮一次全量测试）换成一次直接求值，直接解出确切 fixture 数值。
