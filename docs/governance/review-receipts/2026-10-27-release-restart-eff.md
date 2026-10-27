# RULE-AI-28 独立代码审查回执：Release Restart 效率线（11 产物）

- 审查者 id：独立审查子代理（本 run tool-execution id `05d6b8c60fc5243f53575e6d21ba7760`；运行上下文未披露具名 subagent id，以此 run id 代）
- 时间：2026-10-27 18:0x–18:2x（UTC+8）
- 被审基线 commit：`e535a11ab8c6917d6d5ac2721db7251d5240ad2a`（分支 feat/release-restart-eff-20261027，HEAD 实测一致）
- 工作树：/Users/yyj/lfl-workspace/work/lfl-eff-20261027/repo
- 方法论检索：工具集无 search_records（核对可用工具清单），按纪律"不适用则直接开始"处理
- 父代理补充事实（未经本审查独立复核，采信并留痕）：该基线的 ci.yml/release.yml/runtime service_control.py 三文件与 lfl/main blob 相同，本审查结论对 lfl/main 同样有效

## verdict: **FAIL**（1×P1：产物现状无法通过自身 pyright 门禁；无 P0）

修复 P1（一行级类型修正）后建议快速复验 pyright 三文件 + 全量 ratchet，其余结论不因此变动。

## 产物 SHA 核对（11/11 OK）

清单 /Users/yyj/lfl-workspace/work/lfl-eff-20261027/artifact-sha256.txt，`shasum -a 256 -c` 逐条 OK（a41760e0…ci.yml、00d6c603…finalize-release.yml、691371b1…release.yml、d74c90fc…基线报告、2914310b…release_finalize.py、6310961b…runtime/service_control.py、a57c545c…service_control_derivation.py、6cafa13e…builtin/service_control.py、6ceab2f5…test_lifecycle、ee4a110d…test_argument_contract、e13b5bf1…test_svc_deploy_next_step）。`git status` 7 M + 4 ?? 与清单一一对应。

## P0/P1/P2 表

| 级别 | 位置 | 问题 | 反例/缺失测试 |
|---|---|---|---|
| **P1** | src/llm_loop/tools/builtin/service_control.py:593（新增 T2 代码 `body["updated"]["derived_from"] = {...}`） | pyright 净新增错误 `reportIndexIssue: "__setitem__" method not defined on type "object"`（`body: dict[str, object]` 使 `body["updated"]` 退化为 object）。冻结 ledger 该文件 pyright 条目=0，属净新增债务 | 权威复跑：`check_static_diagnostics.py --tool pyright` 输出 `BLOCK NEW x1` + `BLOCK CHANGED FILE`；基线版本同文件 0 errors。ci.yml test job 与 release.yml gate 均会红。修复建议：先构造完整 `updated: dict[str, object]` 再整体赋给 body（或局部注解），不改行为 |
| P2 | scripts/release_finalize.py:101-103 | latest 承诺检测正则双向缺陷：过窄——"本版本是最新版"探针 False（漏报）；过宽——"the latest release notes"探针 True（误伤英文普通叙述） | 探针：`_LATEST_CLAIM_RE.search('本版本是最新版')==False`、`search('the latest release notes')==True`。该检测仅诊断上报（:321-324 只 print，不阻断不改写），危害有限 |
| P2 | scripts/release_finalize.py:306-312 | `replace_status_block` 只替换第一个状态块（`_BODY_BLOCK_RE.sub(..., count=1)`）；正文若已存在两个状态块，第二个永久残留 | 探针：双块输入 replace 后 `BODY_BEGIN` 计数仍=2。正常写入路径不会产生双块（先 replace 再 prepend） |
| P2 | scripts/release_finalize.py:496-498 | `apply_status_block` 的 published guard（"不是 draft 拒绝改写正文"）未被 `--self-check` 五场景覆盖（S5 只覆盖 sync guard） | 行为本审查已探针补验（code=6、零写、拒绝文案在场），建议补 S6 场景固化 |
| P2 | .github/workflows/finalize-release.yml:28 + scripts/release_finalize.py:419-425 | workflow_dispatch 输入全 ref（`refs/tags/vX`）时 concurrency 组名错位（组名在 workflow 层先于脚本求值）；但 `validate_tag_or_die` 的 `_TAG_RE` 拒绝斜杠，在任何 gh 调用前 EXIT_GUARD 零写，single-writer 不会被实际破坏 | 防御性/体验问题：错误输入只会得到 guard 报错而非静默绕过互斥 |
| P2 | .github/workflows/ci.yml:23-25 | schedule 与 push main 共组 `ci-refs/heads/main` 且 cancel-in-progress:true，nightly 评测与 main push 互相取消（符合"按 ref 取消"的既定意图，属隐性取舍，留痕供决策知悉） | — |

## A–J 逐项结论

- **A 零副作用：PASS（代码路径亲读，非仅测试断言）**。工具面：`execute`→`_service_control_contract_error`（:79-138 纯校验，docstring "before any side effect"）→`_update` code_root/reason 校验（纯）→推导失败即纯 `_failure` return（:518-531）→之后才是 `_publish`（:534）内 `store.compare_and_swap`（:482）。CLI 面：`main` update 分支 `ManagedServiceDeploymentStore.__init__`（runtime:985-996）只算路径（`AdmissionBarrierRegistry.__init__` admission_barrier.py:136-138、`EvidenceRef.__init__` :738-739 同为惰性；写动作全部在 `lease()`/`lifecycle_lease()` 的 mkdir/lock 与 CAS 内）→推导失败 print NEEDS_TARGET + `return 2`（runtime:4323-4350）→之后才 `store.read()`（只读）/`build_deployment`/`compare_and_swap`。
- **B 无第三份实现/旧名残留：PASS**。`git grep -n "_derive_restart_target\|def derive_restart_target\|restart_target or"` 全树 0 命中；`derive_restart_target` 实现仅 derivation.py:47，import 仅 runtime:54 与 builtin:33 两处。
- **C ci.yml 收敛不伤 release 触发：PASS**。ci.yml push.branches:[main]（:13-15）→tag 推送不再触发 CI（预期）；release.yml `on: push: tags: ['v*']`（:11-14）未被本次改动触碰，仍由 tag 独立触发；ci.yml 其余 169 行零改动（diff 仅 +8 行触发/并发）。
- **D 同 tag 组名严格相等：PASS**。tag push 时 release.yml `release-${{ github.ref }}` = `release-refs/tags/vX`；finalize `release-${{ format('refs/tags/{0}', inputs.tag) }}` 裸 tag 输入拼出同一字符串（YAML 解析回显两者原文核对）。全 ref 输入形态被脚本 `_TAG_RE`（拒斜杠）在统一入口 `main()` 的 `validate_tag_or_die` 拦截，先于任何 gh 调用，不构成互斥破洞（残余见 P2 表）。
- **E 资产集比对：PASS**。manifest 自身排除三处一致（collect_local_facts:434、sync:470、finalize 比对:555）；未申报资产拒绝（探针：注入 rogue-extra.bin → code=4、保持 draft、零新增写、报"多余资产: rogue-extra.bin"）；Release 缺 manifest 资产时 :519-523 先拒，download 后文件缺失有 OSError/JSONDecodeError catch（:527-532）→EXIT_MANIFEST_INVALID。
- **F required 判定：PASS（v0.6.37 模式已堵）**。探针：`LFL-…-signed.pkg.sha256`→平台 macos_arm64、required=False → 仅上传它时 macos_arm64=pending（不误判 ready）；wheel→any、required=True → linux_x86_64=ready（不会被 wheel/sdist 卡死）。机制：`_OPTIONAL_PATTERNS`（:92-96）+`PLATFORM_COVERAGE`（:77-81）+`platform_has_required`（:131-137）。
- **G latest 检测：FAIL（P2 级，仅诊断面）**。见 P2 表第 1 条；`find_latest_claims` 已正确排除状态块自身（:317），published 块内"最新可用版本"不误报。
- **H 幂等与 published 只读：PASS（带 P2 边角）**。单块重复替换 once==twice（探针）；`apply_status_block` 内容未变时零写（:502-504）；published 后 sync/body 双 guard 拒绝（:456-458、:496-498；body guard 本审查探针补验 code=6 零写，S5 覆盖 sync）；finalize 对已 published 幂等重放 EXIT_OK 零写（:515-517，S5 验证）。双块残留边角见 P2 表。
- **I 测试断言行为而非文案：PASS**。零副作用测试断言 `store.read().generation==1`、`spawned==[]`、`store.actions_dir.glob("*.json")==[]`（test_lifecycle:250-252、:264-266；CLI 面 :300-302；contract:84-85 `store.read() is None`），NEEDS_TARGET 文案断言只是附加。derived_from 仅推导时标注/显式不标注均有正反向测试（lifecycle:129-133、:272-279）。
- **J 无既有调用方静默破坏：PASS**。`git grep "service_control(action=update"` 4 命中均为示例命令文本（runtime:2374、builtin:524）、测试断言（contract:84）与历史结果记录（RESULT-20261017，显式 target=web）；CLI/docs/scripts 操作面无不带 target 的 update 调用点，"首次失败清单"为空。

## 独立复跑真实输出（原样）

1. pytest 五文件：`108 passed in 5.50s`（exit 0）
2. pyright（pyproject `[tool.pyright]` include=["src"]、basic、py3.13；按父指示三文件）：
   `src/llm_loop/tools/builtin/service_control.py:593:13 - error: "__setitem__" method not defined on type "object" (reportIndexIssue)` / `1 error, 0 warnings, 0 informations`；基线版本同文件 `0 errors`；全量 ratchet 门禁（真实完成，非超时降级）：`R9 pyright: historical=45, current=12, new=1, resolved=34, …` + `BLOCK NEW x1: …builtin/service_control.py reportIndexIssue` + `BLOCK CHANGED FILE`
3. `release_finalize.py --self-check`：`self-check 汇总: 5/5 场景通过`，EXIT=0
4. YAML safe_load：三 workflow 全部 OK（on/concurrency 回显见审查记录：ci=push[main]+PR+schedule+dispatch、release=push tags v*、finalize=workflow_dispatch(tag)；组名原文比对通过）
5. 附加：ruff 四个改动 py 文件 `All checks passed!`

## 基线报告抽查（docs/LFL_Release_Restart_Baseline_20261027.md，6 条全部成立，无 P1）

1. "release pytest 是 PR pytest 超集"：release.yml:55 `-m "not real_llm"` ⊇ ci.yml:58 `-m "not real_llm and not serial_signal"` ✅
2. pyright `--require-complete` 仅 release 侧（release.yml:53 有、ci.yml:56 无）✅
3. `.github/` 无 workflow 实际调用 ci_gate.sh（grep 3 命中均为注释/步骤名）✅
4. `review-receipts` 零脚本消费（src/scripts/.github grep 0 命中）✅
5. 基线 ci.yml `on: push:` 无过滤（`git show HEAD` 证实，即本次收敛的动机）✅
6. "不自动重跑"行号 HEAD:3432 精确命中（工作树同内容偏移 +4，由 import hunk 解释；报告自述按 origin/main 行号）✅

## 建议采纳清单

1.（P1，合并前必须）修 builtin:593 类型错误：`updated` 局部 dict 构造完整后整体放入 body；修后跑三文件 pyright + 全量 ratchet 复验
2.（P2）latest 正则补 `最新版\b` 一类模式并考虑收窄英文匹配至 `latest (release|version) of (this|the) package|本发布`——注意该检测只影响诊断输出，收窄优先于扩宽
3.（P2）self-check 增补 S6：published 后 `body` 子命令 guard + 未申报资产拒绝场景（后者本审查已探针验证，缺的是脚本内固化）
4.（P2）finalize workflow 输入描述注明"只接受裸 tag（vX），全 ref 会被 guard 拒绝"
5.（P2，可选）`replace_status_block` 对多块输入给出告警日志

## 未验证项（UNVERIFIED）

- GitHub Actions 平台运行时行为（tag push 实际触发、concurrency 组实际互斥、`gh` 真实网络路径）——本审查仅做语法解析/字符串等价/脚本单测级验证，未推送、未触网（符合只读纪律）
- `body`/`manifest` 子命令对真实 gh CLI 的交互（FakeGh 内存模型已覆盖接口语义）
- macOS 签名机标准流程全链（finalize-release.yml 注释 :7-10 描述的 3 步人工流）未实测
- 父代理"三文件与 lfl/main blob 相同"之事实未独立复核（remote 陷阱：origin=legacy，本任务不涉 push，未取 lfl ref）
- ci.yml 60-177 行（linux-installer/nightly/serial/ambient jobs）逐行精读未做——diff --stat 证实零改动（+8 行仅触发/并发），风险面限于上述

## 审查纪律声明

- 未修改任何被审产物：`git diff` 于 11 产物与冻结时一致（SHA 复核 11/11 OK）
- 未 commit / 未 push；唯一写入 = 本回执文件；临时产物仅 `.smx/review-pyright-gate.log`（.smx/ 为 gitignore 路径，不入 git status）
- RULE-AI-28 独立性：审查者非四个执行子代理之一，所有复跑在本 run 独立执行

---

# 窄复审（2026-10-27）

- 审查者 id：`subagent_c18821b861f4`（本 id 由父代理在 spawn 回执中提供，非本审查自行生成）
- id 记录更正（父代理调度记录补登）：初审审查者 id 应为 `subagent_6d9c02601f59`；初审回执开头原写的 run tool-execution id `05d6b8c60fc5243f53575e6d21ba7760` 属错误记录方式，**作废**（仅更正 id 记录，初审正文其余内容一字未动、全文保留）
- 时间：2026-10-27 晚（UTC+8）；被审基线：commit `e535a11ab8c6917d6d5ac2721db7251d5240ad2a` + 未 commit 工作树（与初审同一冻结基线）
- 方法论检索：本 run 工具集无 search_records，同初审按"不适用则直接开始"处理

## 覆盖范围声明

只审：① 原 P1（builtin/service_control.py:593 类型错误）修复；② ci.yml concurrency；③ release_finalize.py 三处（latest 正则 / 多块替换 / S8）；④ 上述三文件改动的 ruff/pyright 新问题。初审已 PASS 的 A/B/C/D/E/F/I/J 结论与基线报告抽查**不重审**，维持初审结论。

## 被审产物 SHA v2 核对（11/11 OK）

清单 /Users/yyj/lfl-workspace/work/lfl-eff-20261027/artifact-sha256-v2.txt，`shasum -a 256 -c` 逐条 OK（ci.yml、finalize-release.yml、release.yml、基线报告、release_finalize.py、runtime/service_control.py、service_control_derivation.py、builtin/service_control.py、三个测试文件）。`git status` 7 M + 4 ?? 与清单一一对应（本回执文件不在被审清单内，为本次唯一允许写入）；`git diff HEAD --stat -- pyproject.toml` 为空 → 无 pyright/ruff 配置放宽。

## verdict: **PASS**（原 P1 已关闭；原三条 P2 已关闭；无新增 P0/P1/P2）

P1 关闭唯一采信证据 = 下方全量 pyright ratchet 独立复跑 new=0 且 touched files clean。

## 逐条关闭状态

| 原项 | 状态 | 依据（本窄复审独立复验） |
|---|---|---|
| P1 builtin/service_control.py:593 pyright reportIndexIssue | **已关闭** | 修复改为局部 `updated: dict[str, object]`（:579-593）组装后整体赋 `body["updated"]`（:595）。键集/层级/出现条件与原意等价：action_id/target/generation/git_head/webui_artifact_sha256/reason 六键 + `derived_from` 仅 `if derivation is not None` 时位于 updated 内（:587-593），显式传参不出现；后续 live_identity_hint/convergence 逻辑不变（:601-605）。文件内无 `type: ignore`；三处 `# noqa: BLE001` 均为 HEAD 既有（HEAD:287/413/552，工作树 diff 中 noqa 变更数=0）。全量 ratchet：`R9 pyright: historical=45, current=11, new=0, resolved=34, changed_file_diagnostics=0 … PASS (… touched files clean)`，status=complete（非超时降级），analyzer pyright 1.1.411 与冻结一致 |
| P2 latest 正则双向缺陷（release_finalize.py:107-113） | **已关闭** | 正则收紧为"取用类动词引导 latest release/version/build（≤48 字符）"∨"latest … available 可用性宣告"∨中文"最新可用/最新版(?!权)/视为最新/作为最新"。独立探针：初审失败对已反转——`'本版本是最新版'`→True（原漏报）、`'the latest release notes'`→False（原误伤）；另测 `'latest release available now'`→True、`'see the latest changes'`/`'最新一次提交'`/`'最新版权信息'`→False。脚本内固化正 5/负 4 样本（:727-739），全部按预期通过（S6）。留痕观察（非缺陷）：中文动词+英文名词跨语形态 `'请下载 the latest version'` 不命中，符合该检测"宁漏勿误伤、仅诊断不阻断"的既定设计取向 |
| P2 replace_status_block 只换首块、双块残留（:316-330） | **已关闭** | 改为 `_BODY_BLOCK_RE.sub` 回调：首个匹配位置写新块、其余残留块返回空串清除。独立探针（双块+块外正文+尾段）：输出以 NEWBLOCK 开头（首块原位）、NEWBLOCK 计数=1、旧 BEGIN 计数=0、`KEEP-ME` 与尾段文字保留；空正文→仅新块、无块正文→置顶拼接（回归不变）。S7 固化两次写入幂等且第二次零写（edit_body mutations 计数=1） |
| P2 published body guard 缺 self-check 覆盖 | **已关闭** | 新增 S8（:774-786，场景表 :798）：FakeGh draft=False 下 `apply_status_block` 返回既有 `EXIT_GUARD=6`（:121 常量，非新退出码），断言 `("edit_body",) not in fake.mutations`（零写）与 body 原文不变；guard 分支（:514-516）在 tempfile/edit_body 之前 return，代码路径上不可能调用 edit_body。self-check 8/8 PASS、EXIT=0 |
| P2 finalize workflow 全 ref 组名错位（原表 :26） | **留痕不修** | 本轮未改动该行为；维持初审判断——`_TAG_RE` 拒斜杠在任何 gh 调用前 EXIT_GUARD 零写，single-writer 不被实际破坏，防御性/体验问题留痕 |

## ci.yml concurrency 复核（D5 注释 :21-27 与实现一致）

`group: ci-${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}` + `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`。按 GitHub 语境常量逐事件推演：PR 事件 ref=refs/pull/N/merge（同 PR 稳定）→ 同组且 cancel=true，旧跑取消 ✅；push main → 组 ci-CI-push-refs/heads/main 且表达式求值 false，push 间不互取消 ✅；schedule（ref=默认分支 refs/heads/main）→ 组 ci-CI-schedule-refs/heads/main 与 push 组字符串不同 → nightly 不被 push 打断 ✅。表达式为 GitHub 官方 context/运算符语法，yaml.safe_load 回显原文一致（见下）。原 P2 表中"schedule 与 push 共组互取消"的隐性取舍随本次改动消除（该项无需再列）。

## 新增扫描（三修订文件）

- ruff：`uv run --no-sync ruff check src/llm_loop/tools/builtin/service_control.py scripts/release_finalize.py` → `All checks passed!`（ci.yml 为 YAML，不适用 ruff；其有效性由 safe_load 覆盖）
- pyright：全量 ratchet new=0、changed_file_diagnostics=0（含 builtin/service_control.py 与 untracked 的 release_finalize.py/derivation.py），无新问题

## 独立复跑真实输出（原样摘录）

1. `uv run --no-sync python scripts/check_static_diagnostics.py --tool pyright`（完整跑完，后台执行规避 60s 工具超时，日志 .smx/rereview-pyright.log）：
   `ratchet HEAD=e535a11ab8c6d661 ledger_sha256=b7ed6806d661 (frozen b7ed6806d661)` / `analyzer pyright: actual=pyright 1.1.411 frozen=pyright 1.1.411` / `R9 pyright: historical=45, current=11, new=0, resolved=34, changed_file_diagnostics=0, changed_python_files=7` / `R9 pyright: PASS (historical debt visible; no new errors; touched files clean)` / `R9 pyright status=complete` / `EXIT=0`
2. `uv run --no-sync python -m pytest tests/unit/test_lifecycle_update_single_action.py tests/unit/test_svc_deploy_next_step.py tests/unit/test_service_control_argument_contract.py -q` → `84 passed in 3.23s`，EXIT=0
3. `uv run --no-sync python scripts/release_finalize.py --self-check` → S1–S8 逐项 PASS，`self-check 汇总: 8/8 场景通过`，`EXIT=0`
4. ci.yml `yaml.safe_load` 回显：`on = {'push': {'branches': ['main']}, 'pull_request': None, 'schedule': [{'cron': '0 20 * * *'}], 'workflow_dispatch': None}`；`concurrency = {'group': 'ci-${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}', 'cancel-in-progress': "${{ github.event_name == 'pull_request' }}"}`

## 未验证项（UNVERIFIED）

- GitHub Actions 平台运行时行为（concurrency 组实际互斥/取消、表达式平台端求值、tag push 触发、gh 真实网络路径）——仍仅语法解析/字符串等价/单测级验证，未推送未触网
- `github.workflow` 取 workflow name "CI" 为静态推演，未在平台实测组名字符串
- latest 正则仅覆盖脚本内 5+4 样本与本审查 5+4 外部探针，非穷举语料
- 父代理提供的 subagent id（`subagent_c18821b861f4` / 初审 `subagent_6d9c02601f59`）为调度记录采信，本审查无法独立核验登记库
- 初审 UNVERIFIED 各项（lfl/main blob 相同、ci.yml 60-177 行逐行精读等）不在窄复审范围，状态不变

## 审查纪律声明

- 未修改任何被审产物：SHA v2 复核 11/11 OK（复跑在 SHA 核对之后执行，产物未被触碰）；未 commit / 未 push
- 唯一写入 = 本回执文件的追加章节；临时产物仅 `.smx/rereview-pyright.log`（gitignore 路径，不入 git status）
- RULE-AI-28 独立性：本窄复审所有复跑与探针在本 run 独立执行；一处护栏交互如实记录：heredoc 直传解释器被安全硬阻断（E6），改用 `python -c` 等价执行，不影响结论
