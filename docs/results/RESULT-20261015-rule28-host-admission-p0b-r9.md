# RESULT — Rule28 P0-B Host 审查准入：独立审查与原生 R9（2026-10-15）

## 一、交付边界

- **源码隔离提交**：`7e4efb3dd004ff2296afd0b97819c731e5036e2b`，分支 `fix/rule28-host-admission-20261015`，父提交 `8b3494c1b80f088fe56eb990dcd238f2b2c8f70f`。
- 源码提交严格包含 **10 个文件**；冻结 `git diff HEAD^ HEAD --binary` SHA-256：`2b8e80687ec64f06410dc36596b3c138633bdd8df78b3373479055519163402d`，字节数 **102781**。该提交差异与 Reviewer6 所见的完整补丁逐字节一致。
- **main** 在收尾核验中仍为 `db4aaa8565ea0d0cc061b12e5701f5398b53698e`；未合并、未推送、未发布、未重启。**隔离分支测试通过不代表生产生效**。
- 独立审查元信息见 `docs/governance/receipts/RECEIPT-20261015-rule28-host-p0b-glm53-independent-review.json`；原始完整审查 JSON 和补丁在忽略的运行数据目录保存，不把潜在本地绝对路径或审查全文纳入 Git。

## 二、实际新增的 Host 前置准入

- `ToolRegistry.execute` 在受保护的全量 `pytest` / `ci_gate.sh`、已识别 `git push` 的实际进程启动**之前**校验 Review Admission；失败直接 BLOCKED，前后台命令同一入口。
- `BrowserActionAdapter.execute` 取得语义对象与页面快照后、真实 `actuator.dispatch` 之前核验明确的文稿发表按钮。`BrowserSemanticExecuteTool` 与 `browser_operate` 均委托这个物理分派边界，已用真实工具调用和零派发/合格后单次派发测试证实。
- `review_admission(start/status)` 由 Host 冻结实际补丁或页面内容，启动只读独立 `glm/glm-5.3` 子代理；`SubAgentRunner.review_isolated` 阻止父代理 steer 或 durable 消息注入；仅实际完成的进程内 child 终态、独立 PASS、唯一一致严重度计数、当前 SHA/父会话/动作与目标、EventStore 审计写入全部匹配后签发一次性内存资格。模型文本或任意 JSON 不具放行权。
- 常规只读命令、定向测试、草稿编辑和无关浏览器按钮不应被误拦；不替代既有用户授权；没有增加通用 Provider 控制或预算架构。
- 冻结代码材料不做有损摘要，完整上限 **128KB**；源文件敏感路径拒审、Git diff 关闭 `textconv`/外部差异驱动，并使用 `git --no-replace-objects`。

## 三、独立 Reviewer 的真实资格与失败历史

前序五次 Reviewer 结论没有篡改或冒充合格：第 1 轮 REVISE 暴露父→审核者 steer；第 2 轮专业 PASS 但计数/SHA 行不合格；第 3 轮 REVISE 暴露 shell 包装与浏览器语义入口证据缺口；第 4 轮机器 PASS 仅覆盖旧源码，随后 R9 故障触发补丁变化；第 5 轮专业 PASS 但全文计数冲突而 NOT_QUALIFIED。以上原始结果在 `data/rule28-host-independent-review/` 以 `attempt1` 至 `attempt5` 文件保留。

**第 6 轮：**真实独立 GLM-5.3 Reviewer、子代理 `subagent_154e422aff21`，父会话 `review-parent-rule28-host-a6-20261015`，进程内 `review_isolated=true`；**唯一** EventStore terminal `90e423da-dc9a-4ff5-baca-000574e8dc4c`，状态 completed，result id `result-befb53544e444a3392d858649424af1a`；最终 **VERDICT PASS / P0=0 / P1=0 / P2=5**，机器资格 **PASS**；准确对应 SHA `2b8e80687ec64f06410dc36596b3c138633bdd8df78b3373479055519163402d`。文本 SHA-256 `596f481b4d33c84d99b0cad4c1e45dbfe88060763c82407ddf744f4368584d74`，原始记录 SHA-256 `bb2958448372b384f3e414f789fc10f50e9edffc385879dbee155675e5f3f59e`。P2 主要包括 `xargs` 等未知包装的识别缺口、个别子集 `pytest` 误拦、需持续关注的工作目录参数契约、表单非 click 发表入口和固有 TOCTOU 窗口；**不是全域防旁路证明**。

## 四、原生完整 R9：保留失败与最终通过两种证据

**第 1 次完整 R9：真实 exit 1。** xdist **8,821 passed / 146 skipped / 2 failed / 13 warnings**，串行归因仍 **2 failed / 17 passed**，不能解释为全绿。阻断：
1. 新增 `review_host_admission._git` 直接读取 `os.environ`，违反直接环境访问单向棘轮；修为 Git 自身的 `--no-replace-objects`，不扩大环境 baseline。
2. 存量备份测试样本时间写死 `2026-10-08T10:00:00`，到 2026-10-15 已超过 7 天保留期，因此“孤儿临时文件不入扫描”测试错误预期 `pruned=0`；只在该测试内 `monkeypatch` 固定时钟到 `2026-10-09T10:00:00`，**未改生产备份清理代码**。

第 1 次原生日志：`data/rule28-host-p0b-native-r9.log`，SHA-256 `cba777bc92cd2eb2f0701e2e732502495e28c0547bb6dbc06831a227304a57ec`。

**第 2 次完整原生 `bash scripts/ci_gate.sh`：最终 exit 0。** 先重新冻结源码并取得第六轮真实独立 Reviewer PASS，然后原生脚本逐门运行：
- Ruff ratchet PASS：historical=67，current=34，new=0，touched=0；
- Env-pin PASS：857 个测试文件扫描，未声明依赖 0；
- Pyright ratchet PASS：historical=45，current=16，new=0，touched=0；
- WebUI 使用隔离候选源码构建；tier0：**319 passed，8,674 deselected，3 warnings**；
- 4-worker xdist 完整全量：**8,831 passed，146 skipped，13 warnings**，无失败、无需串行降级；
- Guard report：**1 passed，29 deselected**；
- `✅ ci_gate 全链路通过`，shell **exit 0**。

第 2 次完整原生日志：`data/rule28-host-p0b-native-r9-attempt2.log`，SHA-256 **`061093fe6624768b3f9146760261d64e8e50ebcec6495ff4460d103217f1e94c`**。

## 五、测试写入与隔离边界

- 两次完整 R9 各自生成、改写 **18 份** `reports/phase3–6` 下的已跟踪历史报告；每次先验明唯一白名单，再保存原始二进制 diff 到忽略的数据目录，并仅对对应 18 文件 `git restore --worktree`，**没有修改其它 Agent 的 worktree/主仓/未跟踪文件**。
- 第 1 次副作用补丁 `data/rule28-host-r9-test-generated-reports.patch`，SHA-256 `dd35e2b2fe3752057ba841994359f23fb259d60a5fc7bc922d69937912e17305`；第 2 次 `data/rule28-host-r9-attempt2-generated-reports.patch`，SHA-256 `7bd275341e14fe439ad9d610de58f80f19b222a60bf8e613c9d3ced0d0b33348`。
- 测试后源码 staged SHA 不变；10 文件扫描、提交前安全钩子 PASS。代码只在新的隔离分支形成本地 commit，未触碰 main。
- 当前代码未实现“任意 `eval` / `xargs` / shell 包装 / Make 目标 / 内嵌脚本全语义解析”、任何网页平台各种模糊按钮或表单自动发表、所有进程层级的 OS 物理阻断，且审核通过到实际 dispatch 之间有 TOCTOU 窗口。以上必须在后续真实入口资格审计中明确披露，**不能宣称生产三闸全覆盖**。

## 六、收口与下一步

本阶段达到的资格是 **Rule28 P0-B 已识别的 Host 物理入口有本地隔离实现、真实独立合格审查、完整原生 R9 PASS 和可追溯回执**。后续若要纳入 main 并上线，需先核对最新 main 并发差异、权限与现有运行中任务，由用户另行明确授权审查、集成和受控服务切换；本阶段**不合并 main、不 push、不发布、不重启**。
