# GLM-5.3 输出预算耗尽修复（2026-10-17）

状态：已独立审查并本地快进合入main；原版完整R9通过既有serial复核策略。Web generation276已受控重启成功，真实默认GLM请求max_tokens=65536并正常完成；此单元完成，未push。

## 实际事故

- 2026-10-17 14:20:02+08，session `e057407b-f591-45ba-9231-848faef58a91`，call `pcall:6ff45ae567c33ebe87f81b5678ade700`。
- 真实runtime为Web PID8759、release `b9bf967d8c86652e9c4f417375c1c6a330196918`；foreground round1，reasoning_effort=max，provider-visible46970chars，输入15612tokens。
- 实际线上请求max_tokens=16000，provider finish_reason=length、output16000tokens/reasoning15998tokens、provider_truncated=true；正文/工具草稿为零，已投递reasoning47359chars。
- 这是输出预算耗尽，不是输入上下文超过16K或120秒等待超时；本attempt从14:15:31至14:20:02，持续推理后达到长度上限。已保存中断native状态和truncation ref；不把思考尾部冒充完成答案。

## 修改与边界

- 仅针对已有LLMEmptyResponseError的明确`length`/`max_tokens`结束原因，给出输出预算耗尽、报告用量和提高模型专属预算的建议。未知/stop/content_filter空响应不推断该原因，timeout继续保留独立诊断。
- 模型配置计划仅追加`data/providers.local.json /glm/models/glm-5.3/max_tokens=65536`。保留reasoning_effort=max、timeout120；不放大全局默认，不修改其他provider/model、输入限制、Stop、任务预算和重试语义。
- 官方文档（2026-10-17核对）：GLM-5.3默认输出65536、最大131072，始终思考。来源 https://docs.bigmodel.cn/cn/guide/start/concept-param 与 https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3 。仅把最大值作为模型边界，不声明已做本账户128K实测。
- 配置必须走现有provider配置文件锁/CAS和原子替换，只更改一个字段，保存回滚前bytes；registry可热重载，但默认client为启动快照，须受控Web-only重启后核实际请求。不得把文件值或目录reload当运行态已生效。

## 验证

- 回归修复前4failed/4passed；修后8项通过。连同timeout/fault-isolation/model-pool/subagent-output-budget邻接共60passed，exit0。
- Ruff/diff-check通过。原始RED/GREEN与事故脱敏事实保存在本任务ignored data目录并绑定SHA；后续审查/门禁和运行态验证继续追加回执。
- 无实际采用的既有Method卡。本次事实从原始event、当前源码和官方文档重新核验；当前插件未暴露原生search_records/method_manage，不在不相关安装Goal写入状态或伪造评分。

- 独立代码审查回执：`docs/governance/receipts/RECEIPT-20261017-glm-output-budget-code-review.json`，Reviewer为宿主Codex子代理，非GLM-5.3；独立定向43passed，未提前全量。
- 配置持久化回执：`docs/governance/receipts/RECEIPT-20261017-glm-output-budget-config.json`，只变更一个字段；备份私有0600，重载目录成功；默认client尚未重启。

## 完整门禁与阶段冻结

- 受管原版R9已经完成并提交源码`d5f7f3321c99c05d3fe8847b1127166f310d4615`；精确PROBE `d7c458b037259b93c48035f9a5ff798420f5eed4`树与源码提交完全一致。原命令保留期已过，不重跑；从真实提交、wrapper完成标记和原始ci_gate日志恢复终态。
- Ruff/env-pin/Pyright/五规则/安全扫描通过，tier0 319passed；全量xdist首轮9378passed/141skipped/1failed（test_m3_four_buckets），原脚本对完整失败文件serial复核2passed后放行，trace schema 1passed。保留并行波动观察，不宣称首轮全绿或已修复该race。
- 完整回执：`docs/governance/receipts/RECEIPT-20261017-glm-output-budget-full-r9.json`，含原始日志SHA。后续纯证据提交不改变已审代码指纹。

## 最终合并与运行态验收

- 独立merge Reviewer `/root/glm_budget_merge_review` 真实终态PASS，基线125a90059、精确候选868431905798b43045fe491a36a9ac5abd0dc510。共享r9锁内核SHA/基线/候选干净/路径无交叉，保护main当时8个其他资产bytes、模式和逐路径index，ff后全部一致。没有stash/reset/夹带他人文件。主仓合后同5文件60passed/0failed。
- 从干净候选检出发布，复用与live b9 tracked WebUI完全相同的dist；provenance verifier和dist tree SHA均核通过。现有service_control update显式target=web、expected-generation275；新generation276、唯一action svc-28e2d0527ace483e9857627ed9a74fbe。
- action先waiting_for_idle，再running，最终succeeded；未force或override。新Web PID76553、2026-10-17 15:16:08+08启动、release868431905、manifest max_tokens65536，health=ok。飞书PID25059、Learning PID25550保持原状；这两个既有进程未由本次重启更新。
- 真实默认Web canary无模型override：session4ac1583a-36e6-48cd-90ac-c222113a0d2d，call pcall:8316f67867fea6e1569a1f529e451acf。request.meta与transport.opened同时确认GLM-5.3、max_tokens65536、reasoning_effort=max、timeout120、PID76553/release868431905。返回“预算验证通过”，无工具调用，单轮completed、未截断；shared-current指针前后SHA相同。
- 此验证证明真实请求的预算已生效及普通回答可完成；本次短答没有触及16K/64K上限，不冒称已证明所有长任务恢复率或128K能力。原始失败的47359chars思考/native中断状态继续保留。
- 最终回执：`docs/governance/receipts/RECEIPT-20261017-glm-output-budget-main-web.json`，关联代码审查、完整R9、main保全、配置CAS、部署action和真实请求。源码部署SHA为868431905；后续纯证据提交不改变被测/被部署代码。
