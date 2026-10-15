# Rule28 P0-C：当前 main 集成资格、物理入口审计与受控上线准备

日期：2026-10-15。**结论：ISOLATED_QUALIFIED_BUT_NOT_RELEASE_AUTHORIZED；三闸全域生产资格 NO_GO。**

## 1. 集成事实与源代码

- 本阶段以创建隔离工作树时的 `main=db4aaa8565ea0d0cc061b12e5701f5398b53698e` 为冻结基线。取 P0-A 源码 `24a99fa26` 与 P0-B 源码 `7e4efb3dd`，在新分支 `fix/rule28-p0c-current-main-20261015` 按序无冲突集成。
- 定向 P0-C RED→GREEN 修复明文 `xargs` 中受保护 git push/全量 pytest 的非直接执行绕过（**只拒绝不明确的目标资格，不假装能推演任意 shell**）；修复 `pytest -k ''`、`python -m pytest -m ''` 空筛选误判，保持定向/无关命令可用；增加真实 Registry 物理派发前 BLOCKED 与 Factory Full/Compact `review_admission` 可见性。
- 本地隔离源码提交：`7e6cf11346a079a769d51129c9f2572757533053`，22 文件；源码完整二进制差异 SHA-256 `ef0b15dbdbbf10cd6011adf46b7e333616a897cf7ab1e3e6370a415e00bbbca1`、字节数 152674，与独立 Reviewer 完整输入逐字节一致。
- 主工作树和 Rule31/Jev 其它工作树及其未提交文件均不曾为本任务重置、改写或合并。

## 2. 实际三类入口与覆盖边界

详情和上线判断见 `docs/PLAN-20261015-rule28-p0c-entrypoint-qualification.md`：

1. ToolRegistry 经 `execute_command` 执行的明确全量测试或 Git push：真实 spawn 前审核；`retry_tool` 经 `registry.execute`，安全路径不缩水。
2. 明确文稿编辑器的 Publish/发表按钮：`BrowserSemanticExecuteTool`、`browser_operate` 都经 `BrowserActionAdapter.execute` 审核，物理 actuator 前否决。未审零派发、审查后一次派发均有测试。
3. 本实现未覆盖任意脚本与 `xargs` 动态构造/DSH 子进程内部、直接对外 HTTP/API/CDP 或表单回车发表的所有路径；审查资格与物理执行间存在 TOCTOU。**不能宣称对所有代码测试/push/文章发表的 OS 级全域硬阻断**；不应通过过度禁止普通 Agent 工具来伪造此资格。

## 3. 最新独立 GLM-5.3 审核（整包、无旧资格复用）

- 首次真实 Reviewer `subagent_7371cd27f8db` 在长补丁推理后 `LLMEmptyResponseError`，终态 failed，机器资格 **NOT_QUALIFIED**；完整失败 JSON 在 `data/rule28-p0c-qualification/glm-child-review-attempt1-empty-response.json`，SHA-256 `982f38a25001d1818f59e96ba61a2ac6e22f8ebdd4337a9d363194659e605f39`。未据此运行全量。
- 第二次使用**相同整包 SHA**、有界较低推理档/更多输出预算，真实独立 GLM-5.3 子代理 `subagent_163729fd0363`，parent `review-parent-rule28-p0c-integration-a2-20261015`、`review_isolated=True`，唯一 EventStore terminal `c4885a0c-af52-4dfc-98a8-f630a6850c15`，状态 completed。
- 结果 **VERDICT PASS、P0=0、P1=0、P2=2、qualification=PASS**。原始审核完整回执 `data/rule28-p0c-qualification/glm-child-review.json`，SHA-256 `0f0cd15b96552e5416de78fadfde397b90c29b365538dc6d8212c382d5c48188`；全文 SHA-256 `31bc139d63ad712c8e8348fb2fd78504c1ec4c05eb10dec4c34fe36e0d4da25f`。两项 P2 是不可达重复 return 和两个 workdir 解析位置的未来漂移风险，未影响当前实际行为。
- 不能将之前 P0-A/P0-B Reviewer 的 PASS 或旧 R9 取代这一轮 22 文件整包独立审查。

## 4. 真实原生全量 R9

- 源码审查合格且无并发 CI 时执行原版 `bash scripts/ci_gate.sh`，真实 **exit 0**，没有 quick/跳过/改 baseline。
- Ruff PASS（new=0、touched=0），Env-pin PASS（857 测试文件扫描），Pyright PASS（new=0、touched=0），WebUI 候选独立构建。
- tier0 **319 passed / 8685 deselected / 3 warnings**；全量 xdist 四 worker **8842 passed / 146 skipped / 13 warnings**，无失败、无 serial 降级；Guard report 1 passed / 29 deselected。
- 完整日志 `data/rule28-p0c-qualification/native-full-r9.log`，SHA-256 `25f08441e6b912e589570a45e821cb597838114ee29533d699d149170c702fa2`。
- R9 自身更改了恰 18 份 `reports/phase3…phase6` 既有报告；已核对白名单后将全部差异归档为 `data/rule28-p0c-qualification/r9-generated-18-tracked-reports.patch`（SHA-256 `8861118e0d50df1111b3c0ba97f9ff406fa6f242b5752d6272b1f214c1dc3a45`），**仅恢复这些报告**；审查前后源码 SHA 未漂移，源提交后 tracked clean。

## 5. main 前进与可合并性 ≠ 新 main 已验收

- 原生全量期间 `main` 又增加 6 个 Jev/Knowledge 提交，到 `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`；变更路径 134 条，与本 P0-C 22 条**直接文件重叠 0**。
- 对当前 main 和已提交的隔离候选执行只生成临时树的 `git merge-tree --write-tree`：无冲突，模拟合并树 `3dd0fd7ff0ba3664b854bea5c8daaa553f2d026a`；**没有真正 merge、commit main、push、发布或 restart**。
- 即使没有直接文件冲突，知识/任务运行时新增变化可能造成语义耦合；对 `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac` + Rule28 的**联合审查与原生完整 R9 仍未执行**。故不得称它已取得最新 main 生产上线资格。

## 6. 生产三通道和下一批资格

- 检查时 live Web/Feishu/Learning 均绑定 `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`（manifest identity_ok=true）；**均非** P0-C 的源提交。
- 下一批必须先以当时冻结的 main 做受控 forward-port 并重新审核完整集成 SHA、同一候选原生 R9；补齐 DSH/间接 Git push/非 click 公开发表的真正物理入口证据，或者用明确声明的分阶段适用范围取得用户审批；先 Web-only canary，核对真实拒审+合格放行、in-flight 会话与回滚能力，再考虑其它通道。
- 用户在本阶段没有批准合并 main / push / 生产发布 / 服务重启；**这些操作均未执行。**
