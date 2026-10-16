# Rule31 — independent GLM-5.3 source review receipt

Date: 2026-10-15. Goal: `d0a3a009-34d8-4f71-a957-60f0e3254249`.

## Frozen reviewed source

- Branch: `fix/rule31-current-main-20261015`; baseline `db4aaa8565ea0d0cc061b12e5701f5398b53698e`.
- Frozen candidate: 8 staged files, **24,049 bytes**, Git patch SHA-256 `705c094eb0c4b3d6bc82a69bacc0190e0d126d30df8eb9094cc10ddedd681e4f`.
- Subsequent local code commit `9c75e91bac76049eb0e9e131f4fd27d32a0ae5bf` verified to contain **exactly** the same bytes and digest.
- This is independent code-review qualification only; not merge/push/deployment/restart permission.

## Reviewer identity and real terminal

- Model: `glm/glm-5.3`, new native child `subagent_b94885b10d36`; parent `review-parent-rule31-current-main-20261015`.
- Child state: `completed`; result id `result-26c3ae187c4b4c94ae9749824d641e7d`.
- Exactly one real EventStore `subagent.terminal` event `abbc561d-8f9b-4c87-850b-c1e15379d954`; parent also checked a live in-process `done_event` and result identity.
- Separate test-only parent process, private EventStore/SessionStore, no registered tools, `required_tools=[]`, one round, no parent steering.
- The reviewer received the **complete immutable 8-file patch**, current main Rule31 SoT including the D3 promotion/correction sentence, and the unchanged backup retention implementation excerpt. It did **not** inspect the entire repository or run tests.
- Verified verdict: **PASS** (P0=0, P1=0, P2=5). The strict final verdict/count/sha lines and exact patch SHA matched.
- Raw immutable evidence (ignored, not staged): `data/rule31-current-main-independent-review/glm-independent-review.json`, SHA-256 `35d8f561383c74c74501838a85085b52c67310cec3896aa3b296d9cea7aa6128`; model report SHA-256 `262784b314747d06cd186c3f0b0a788bdf089c7dac77096a0dedaaff4627eff6`.
- Important limitation: baseline SubAgentRunner lacks the newer experimental `review_isolated=True`; this run used a separate parent context and no tools/steering. Do not claim an OS-separated reviewer or independent full-tree inspection.

## Full independent child report

## 独立审查分析（只读，未运行任何测试）

**1. RuleIndex H2 同级截断（rule_index.py:91-94）**
逻辑正确：`_SECTION_HEADING_RE = ^##[ \t]+` 只匹配 H2（"###" 因第三字符为 # 不匹配），从 `match.end()` 向后搜索到下一个 H2 即截断，嵌套 H3 保留在 Rule 段内；连续 Rule H2 场景与旧行为等价，无回退。两点隐患（均 P2）：
- 正文/代码块内行首出现的 `## xxx`（如 fenced code 中的 Markdown 示例或 shell 注释）会被误判为章节边界提前截断，projection_complete 仍为真，属静默截短风险；
- 未消费 `_RULE_HEADING_RE` 的 `matches` 列表后续逻辑（如 count/索引）若仍假定旧 end 语义，patch 上下文不足以完全排除，但可见 diff 内自洽。

**2. Rule31 有界检索工具描述（registry_introspection.py / registry.py）**
Full 与 Compact 描述均含 "≤2类/每类≤5/同一任务窗口/简单" 关键词，与新 SoT 第 1 条一致；保留"仅以返回的 stable ref 水合、不猜 ref""适用性由模型判断"，未引入程序强制检索或自动裁决，模型代理权保留，符合 Rule31 语义（描述层条款化，无新程序角色）。测试 `test_rule31_bounded_discovery...` 同时校验 full/lazy schema 与 FakeLLM 首包 tools 描述，覆盖到位。注意其依赖 `_mk/_capture_tools` 等既有 helper，patch 外假定可用（上下文未展示，接受为既有基础设施）。

**3. 台账 31/32/33 记账（rule-presence-ledger.md）**
新增 RULE-AI-31 正式行，内容与当前 SoT（含 D3 晋升不清零口径的正文语境）一致；Rule32/33 原行保留未篡改。header `records=37` 与脚本全文去重 ref 口径对齐，且显式披露"37≠正式规则数（33）/真实登记项（36）"，未放宽或欺骗测试。新测试断言 header 数值 == 脚本 `len(report.records)`，形成机械一致性锁，防止口径漂移。P2：`_load_audit().inventory(generated_at="2026-10-15")` 的参数签名未在 patch 中可见，若 audit API 不接受该 kwarg 测试将 error（属测试自身失败，非生产缺陷，但 BLOCK 级证据不足，降为 P2 待运行验证）。

**4. 备份耐久性测试时效修复（test_backup_store_durability.py:285-287）**
方向正确：仅改受影响测试的 fixture 为 `backup_module.system_local_now().isoformat()`，与生产 `cleanup()` 使用同一 `system_local_now` 时钟源，时区天然一致（同为本地时区 ISO 字符串，`datetime.fromisoformat` 往返对称），不触碰生产保留逻辑，属最小修复。此前 R9 的 1 failed（2026-10-08 fixture 跨 7 天 cutoff）根因与该修复吻合。P2：若 `backup_module` 名未被该测试文件导入则 NameError（patch 未含 import，风险低因上下文提示模块别名已存在）；另外 now 与断言间的午夜翻转竞态理论上存在但影响为恰好压线，可忽略。

**5. 浏览器 fail-closed 负例测试（test_browser_attestation_v01.py）**
保留真实 lsof 路径与原断言强度（verdict=="real" + "无监听"），无 mock 判定器，符合 fail-closed 语义不变。P2：bind 后不 listen、由 with 块关闭端口再到 `attest_port` 执行之间存在 TOCTOU 窗口，他进程可抢占该端口导致 flaky；建议保留 FD 不关闭或加重试，但非正确性缺陷。

**6. 真源 SoT 测试（test_rule_retrieval_contract.py 新增两测）**
合成用例正确验证 H3 保留、非 Rule H2 截断；真实 SoT 用例断言 31/32/33 在 refs、末位规则水合不含 "## 配置扩展/配置生命周期约定"，能随新规则追加自适应（用 refs[-1]）。P2：硬编码断言 "## 配置扩展" 存在于 SoT，若文档章节改名将误红（脆弱但安全方向——失败而非漏检）。

**7. 范围与纪律**
无生产逻辑改动（rule_index.py 为生产代码但属 D3/Rule31 既定精确整合范围），无 merge/push/部署，无新控制架构，最小性良好。D3 晋升不清零句子在 SoT 中保留，patch 未触碰 docs/ai_rules.md，无静默回退。R9 此前 1 failed 已如实披露且本 patch 针对性修复，但我未运行测试，不宣称绿。

**结论**：无 P0/P1。上述 P2（代码块内 H2 误截断风险、inventory kwarg 签名未证、端口 TOCTOU、SoT 章节名硬编码、backup_module 导入假定）建议后续跟进，不阻塞。

VERDICT: PASS
P0=0 P1=0 P2=5
SHA256: 705c094eb0c4b3d6bc82a69bacc0190e0d126d30df8eb9094cc10ddedd681e4f

## Resolution boundary

No blocking severity findings were reported, but the five P2 recommendations remain open. This receipt is not an R9 pass or a production change. Refer to `docs/results/RESULT-20261015-rule31-current-main-r9-closure.md` for the real xdist and serial outcomes.
