---
method_id: ci-job-title-tool-list-is-not-failure-count-infer-from-step-order-d88762e77628
name: ci-job-title-tool-list-is-not-failure-count-infer-from-step-order
description: 用户或通知按 CI job 标题里并列的工具名（pytest + ruff + pyright）默认存在 N 个错误时，先把标题当标签而非失败清单。顺序 fail-fast 步骤里，后段步骤被执行本身就是前序步骤全绿的证明：run 时长≈全套耗时、或失败日志里出现 pytest 进度到 100%，即可把『三个错误』坍缩为『唯一失败步骤』。先用 gh run list 对齐 run 与本地 HEAD，再 gh run view（不带 --log-failed）读步骤级勾叉一步纠正前提，然后只对失败步骤 --log-failed 落盘 grep；workflow/门禁脚本留到要给修复命令时再读。前提是无 continue-on-error/always、非 matrix 并行。
aliases: CI红了怎么知道是哪一步挂的, pytest都跑完了ruff和pyright是不是肯定过了, 门禁job名字带三个工具是不是三个错误, gh run view先看步骤勾叉再拉日志, GitHub Actions 后一步执行了前一步就是绿的吗
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f1dd4ef4-49e8-4389-9298-e25d78ef0f70:0:58c6bd5dbe26dd72eeed
evidence_refs: learning:learn:d8afab425e39
created_at: 2026-11-03T23:56:03.088471+08:00
updated_at: 2026-11-03T23:56:03.088471+08:00
---
## Trigger
CI 失败通知或用户提问把一个 job 标题中并列的多个工具名当作多个独立错误（如『pytest + ruff + pyright 三个错误能修吗』），且该 job 步骤为顺序 fail-fast 执行

## Discriminator
run 自身的结构性证据在拉日志前就已可见：总时长≈全套测试耗时（21m 级）说明挂在链条后段；顺序步骤下后一步被执行（pytest 进度条出现/到 100%）等价于前序 ruff/pyright 退出码为 0。权威判据是 gh run view 的步骤级 ✅/❌ 摘要，无需分别对每个工具取证，也无需先读 workflow 配置

## Short path
- gh run list + 本地 git log：对齐失败 run 的 commit 与时长，确认诊断对象就是本地 HEAD 对应的 run
- gh run view <run>（不带 --log-failed）读步骤级勾叉：把『N 个错误』纠正为『唯一失败的最后步骤』，并在回复里先核用户前提
- gh run view <run> --log-failed > /tmp/ci_fail.log 落盘（防回显截断），grep 'FAILED|short test summary' 拿失败单元 id
- 在落盘日志上 grep 断言行与实际 vs 期望差异，收敛到可命名的失败单元与根因材料
- 仅当产出修复方案需要精确门禁命令时，才回读 workflow/ci_gate.sh 等配置

## Stop conditions
- 失败步骤、失败单元（测试/规则 id）、断言的实际 vs 期望均已从 run 自身回执取得
- 步骤摘要显示多步失败或结构非顺序（continue-on-error、if:always、matrix 并行、job 级取消/超时）时，放弃单步坍缩假设，转逐 job/逐步骤取证

## Verification
- 步骤级 ✅/❌ 与 --log-failed 内容互证：失败日志属且仅属最后一个失败步骤
- 报告中的错误计数 = 实际失败步骤/单元数，而非 job 标题的工具枚举数，并向用户显式说明纠正依据

## Counterexamples
- 步骤带 continue-on-error: true 或 if: always()：后步执行不证明前步绿，必须逐步看退出码
- 并行 matrix/多 job 同时红：一个 job 完成对其他 job 状态零信息，须逐 job 检查
- 单一步骤内一个脚本串跑三件套（如 ci_gate.sh 作为一个 step）：步骤摘要无法区分工具，只能解析日志内部相位/棘轮块
- runner 级取消、超时或基础设施故障：无任何工具正确性可从步骤顺序推断
