# GLM-5.3 输出预算耗尽修复（2026-10-17）

状态：独立代码审查PASS（P0/P1/P2=0），相关60项回归通过，待原版完整R9与合并审查。模型专属65536配置已原子保存并reload；默认client仍待受控Web重启核验，当前不声明全面生效。

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
