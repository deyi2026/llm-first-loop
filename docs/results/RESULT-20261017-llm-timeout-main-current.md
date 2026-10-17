# 超时修复：最新main合并与合入后验证

状态：独立合并审查PASS，已本地快进合入main；源码合并提交为`f9893a3aef71f196039bf06cbe44cd265820baaf`。本阶段源码集成完成，尚未推送、发布或重启生产。

- 合并前main为`ddccf8843e3c0761160eb4dc06781a3f5572ac35`，候选为`f9893a3aef71f196039bf06cbe44cd265820baaf`；执行前两树干净、基线一致，`git merge --ff-only`后确认main等于精确候选，没有冲突解决点。
- 独立Reviewer `/root/timeout_merge_review`（宿主Codex子代理，非GLM-5.3）终态PASS，核验分支提交来历、四文件指纹和最新compaction交叉面。没有回退上游compaction或修改守卫baseline。
- 四文件组合指纹仍为`346563ad78647bbb7556ac04c5e18c61aab1c86355b471edf4979a0bf16408f5`，与有效代码审查、历史完整R9一致。
- 42fe代码基线20文件364passed/0failed/exit0（16.27秒），覆盖超时/重试/取消/settlement/故障矩阵、doctor/config/factory/架构及compaction gate、中断持久化与恢复边界；Ruff/diff-check通过。ddcc仅文档变化，未改变被测代码树。
- 原完整R9是41f基线历史证据；98cd的309项与42fe的364项是新基线focused。独立Reviewer确认compaction没有新增LLM/传输入口或改写timeout、Stop、重试和settlement，按实际交叉无需机械重复全量。不能宣称最新main跑过完整R9。

## 合入后冒烟

- 主仓原位执行5文件：93passed/2failed，exit1。两项失败均在既有doctor测试：用例预期未配置rc1，但主仓有真实`.env`，doctor按源码root解析后返回已配置rc0。fixture只改cwd/环境，没有隔离源码root；原始失败日志保留，没有把它记作原位全绿。
- 主仓只读离线doctor实际返回rc0、ready=true，六项本地先决条件检查均pass；这不验证凭据、模型或远端服务。生产配置保持原状。
- 同一精确提交`f9893a3aef71f196039bf06cbe44cd265820baaf`的干净detached检出使用项目venv执行相同5文件：95passed/0failed，exit0（1.94秒）。超时恢复、故障矩阵、compaction、factory与doctor均通过。
- 两项doctor测试对真实源码配置的依赖登记为测试环境限制，本任务未扩大范围修改doctor。原位与干净检出日志分别绑定SHA256，不能相互覆盖。

## 留痕与边界

- 最终合并回执：`docs/governance/receipts/RECEIPT-20261017-llm-timeout-main-merge.json`，含独立裁决、精确SHA、真实命令、日志指纹与合入后验证差异。
- focused历史回执：`docs/governance/receipts/RECEIPT-20261017-llm-timeout-main-current-focused.json`。其“待审/未合并”字段描述当时快照，由最终回执接续，不改写历史。
- 本任务原始R9、focused与冒烟日志已保全到主仓ignored data目录，逐份核对原SHA；集成分支、原冻结分支和同提交冒烟worktree保留供发布审计。
- 合并时树干净；原位验证期间/之后出现的两个experience usage运行账本更新归属未证实，保持未提交、不恢复、不夹带到本任务证据提交。
- 真实provider恢复率和生产运行态仍待受控上线验证；没有推送、发布、重启或修改当前其他Goal。
