# Rule28 + JEV + Rule31 / main 929c — independent GLM-5.3 code-review receipt

Date: 2026-10-15. Goal: `312ddf41-6e44-4346-8676-c700baba77b6`.

## Exact reviewed candidate and gate

- Frozen main: `929c8d83698fb12f5b2751ee38d52c7ec2045f23`; isolated branch `fix/rule28-jev-rule31-929c-20261015`.
- Local source commit `692ea63a53e124454adae66fe9401a70775576fd`, parent=the above main. Six-file Git patch **21,698 bytes**, SHA-256 `c07138d43a0fc81c3519f10b54f3a2b2a33558f31e13be0b6962b18cdf149220`, verified byte-identical to the exact staged patch supplied to Reviewer.
- Native GLM-5.3 independent child `subagent_1d5656615c27`; private parent `review-parent-rule28-jev-rule31-929c-20261015`, 0 registered tools, 1 bounded round, no parent steering, no worktree write privilege.
- Child terminal state `completed`, result ID `result-8867371eb6b44689b733d114e836ed57`; **one** physical EventStore `subagent.terminal` ID `51e8fb77-c1da-4983-9d47-94d7d0d98c87`; live parent handle `done_event` and result identity cross-checked.
- Machine-verifiable **PASS**, P0=0, P1=0, P2=3; final 3 report lines and full 64-hex SHA verified. Child did not run tests, browse or audit entire workspace; reviewed full patch and relevant current-main Rule28/31 SoT / Host gate excerpts provided by parent.
- Original model/EventStore derived JSON remains **ignored local forensic evidence** at `data/rule28-jev-rule31-929c-20261015/review/glm-independent-review.json`, SHA-256 `718e86c4b239dca7cb49a8f92414e5673d0a5bcf0dcc6a9d845c773f854ad97d`, model answer SHA-256 `24c1cf87aee9a2433aec8ad09f92368110daf9fdbbbbcf7899c2bc2303461459`. This tracked derivative contains no host paths or credentials.
- Reviewer source PASS is a **code quality prerequisite**, not a persistent release/push authorization or proof of physically executing the Rule28 Host review_admission production permit. No push or publish is authorized by this receipt.

## Full independent reviewer judgment

【审查报告】Rule31 main@929c8d8 六文件整合候选，独立只读复核（非执行测试，未跑全量套件）。

1) Rule31 水合边界（rule_index.py:87-95）：原实现以“下一个规则标题”为界，末条规则会吞并后续配置 H2；新实现用 `_SECTION_HEADING_RE`（`^##[ \t]+`）定位任意同级 H2 截断，嵌套 `###` 因第三字符为 `#` 不被误匹配。新测试 test_last_rule_hydration… 断言保留 `### 适用示例`、排除两个配置 H2，且 `search(kind="rule", query="", limit=10)==3` 防止边界回归；test_real_rules_sot… 用真实 SoT 断言 31/32/33 存在、refs 去重、refs[-1] 水合不含 `## 配置扩展`，并经 run_search_records 回执复验。逻辑正确，exact stable ref 水合路径未削弱。P2-a：真实 SoT 测试硬断言 `"## 配置扩展" in text`，SoT 后续重命名该章节会使测试失效（属锚点耦合，非错误，建议改为条件断言或注释声明依赖）。

2) 有界检索与模型自主性（registry_introspection.py:70、registry.py:99）：Full/Compact 描述均改为“≤2类、每类≤5、同一任务窗口不重复、简单问答豁免、零命中不换词”，与 Rule31 第1条一致；明确“适用性由模型判断，不由程序自动采用”，无隐藏自动注入或语义否决——首个模型工具包测试以 stub 注册并核验 fake.calls[0] 描述与 kind enum，证明仅描述承载、无程序强制。注意边界仅是描述性约束，无程序硬上限；但 Rule31 程序角色明示“无新增”，符合规格，不算缺陷。测试未负向断言“无多余注入工具”，属可加强项（P2-b）。

3) 台账（rule-presence-ledger.md）：Rule31 正式行补登，32/33 原文保留；records=37 与正文“真实登记项 36”的口径差异被显式披露为盘点器全文去重把空缺号 RULE-AI-21 计入，测试同步改为校验正式行 `^\| RULE-AI-\d{2} \|` 去重并断言 header==len(report.records)，口径自洽。P2-c：header 37 与叙事 36 并存仍易误读，建议在 header 行内保留已有括注（现已有，可接受）。

4) Rule28/兼容性：Host review_admission、execute_command 闸代码与 SoT 正文未在补丁内改动；工具描述未承诺全局覆盖。JEV 专线文件本补丁未触碰，声明 byte-identical 属上下文断言，本次无 diff 可证——列为待全量 R9 物理门核实项，而非已验证事实。331 focused + ci_gate --quick 属先前执行回执，本 SHA 不得直接借用为通过证明。

结论：无 P0/P1；三项 P2（SoT 章节名硬锚、缺负向“无注入”断言、台账口径叙事差异）均可后续改进不阻断。全量 R9 为尚未执行的物理门，需在合并前完成。

VERDICT: PASS
P0=0 P1=0 P2=3
SHA256: c07138d43a0fc81c3519f10b54f3a2b2a33558f31e13be0b6962b18cdf149220

## Remaining P2 disposition

The P2s are **non-blocking and remain open**:
1. SoT integration test pins the name of the following `配置扩展` H2; future deliberate renames should update the fixture in the same scoped patch rather than weaken the H2 boundary.
2. More explicit negative coverage of “no extra mandatory method/tool injection” is desirable; current physical behavior is bounded description rather than a new auto-apply controller.
3. Source narrative distinguishes 36 formal registered rule rows from 37 discoverable records (gap placeholder included). Report readers should not equate the two counts.

See `docs/results/RESULT-20261015-rule28-jev-rule31-main929c-r9-closure.md` for the actual post-review full R9; the independent Reviewer did not invent a full-suite result.
