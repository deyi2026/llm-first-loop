# 本地模型重复/漂移 · Stage 1 代码级 RED→GREEN 候选

状态：**仅隔离候选；待独立 GLM-5.3 代码审查，未达 R9/发布门禁**。

- 设计：v0.5 独立 GLM-5.3 PASS（P0=0/P1=0/P2=1），冻结 SHA `96220978276263e6511bdc1e4ea0d00278f0398f7554d0ee3e955dd02c88dab1`。
- Goal：`96b13a77-8f83-4022-b2ad-b1c41ff2f876`；实施分支：`fix/local-model-repetition-presend-20261114`；起点：`9c3cc78a98ebf6754ba9ae9f2c701ffd0e671c37`。
- 原始 RED：101 有效工具、32,768 输出预留、28,659 工具 schema tokens、3,698 历史字符；第二次模拟 Provider 发送前丢失最新完整工具交换且无授权 exact-ref，测试 `1 failed / 1 passed`。
- GLM-5.3 单一开发代理：首版 patch 有效输出但 hunk 计数需 `git apply --recount` 规范化；第二轮修订 `finish_reason=length` 且零正文，未被采纳。验收方最小修正了“同 ID 内容变更误认完整”与“软预算误拦”。
- GREEN：在最后投影/重建后、Provider attempt 前核验最新同 Run 完整 assistant→tool 组的**调用名/参数与逐字原始工具回执**。缺失时复用现有无副作用 conservative rebuild，合法时投影真实原文；物理预算/协议不能安全交付且无合格 exact-ref 时，阻止第二次 Provider 发送，`run_incomplete=true`、`provider_sent=false`，不自动重发工具。
- 负向：缺失/截断/改写内容、改参、重复/不完整 ID、跨 Run 旧组、假 evidence://；正向：正常首轮、双工具配对、变化轮询、低软预算下合法 search_archive 恢复。
- 专项：`211 passed`，Ruff 0 错误，Pyright 0 错误；命令/文件 SHA/日志 SHA 见 `docs/governance/receipts/RECEIPT-20261114-local-model-repetition-stage1-GREEN.json`。

## 仍未完成，严禁提前发布

1. **P1 候选缺口**：owner/version/权限/分页核验的 exact-ref **模型可见投影尚未实现**。目前超大工具结果无法原文容纳时会安全 HOLD，不能宣称生产重复问题已完全修复。
2. **独立模型身份核验**：事故请求 Ornith-MLX 名称与现有 `8901` Qwen GGUF 服务身份不一致，不能沿用 MLX 资格或直接改模型配置。
3. **门禁**：独立 GLM-5.3 代码 Reviewer PASS/P0=P1=0 → 原版完整 R9 exit 0 → CI → 经授权 main/push/受管发布；旧 M4-C 未决债务继续 HOLD。

**未发生**：真实事故工具重放、生产 Provider 推理、模型配置变更、main 合并、push、发布或重启。


## 独立代码审查（同一冻结源码，2026-11-14）

真实 `glm/glm-5.3` 独立 Reviewer：单次 Provider 尝试、零工具、
`finish_reason=stop`、`truncated=false`、合法 JSON 且精确候选 HEAD
`92176804187da90e0d495961921f102c0f463951` 和代码 diff SHA
`358e7563aa038acd8ac169e3d967a0a36483c70399c0ec9a5af83bc0fe085d54`
校验通过；**正式 PASS，P0=0/P1=0/P2=3，AC1–AC10 全部 PASS**。

三项 P2（不改写为零）：① active ingress identity 缺失时 guard
可能跳过，建议专门覆盖；② ingress marker 丢失与普通 observation
缺失应分别诊断；③ guard 自身异常与物理容量不足应分别给出原因，
并测试异常分支的结构化 `run_incomplete`。这些是后续补强建议，
不等于本次生产资格。

正式回执：`docs/governance/receipts/RECEIPT-20261114-local-model-repetition-stage1-GLM53-review.json`。
**原版完整 R9 仍未运行**；当前检测到其他 M5E 工作树正在运行
`bash scripts/ci_gate.sh`，本批不得并发干扰。等待其退出后，再对本
隔离候选运行原版完整 R9，必须以真实 exit 0 作为下一门禁。


## R9 首次阻断及根因修复（待重新审查）

原版 `bash scripts/ci_gate.sh` 对旧代码候选
`9367596c9ff7b625e2fc13eed3581f11815b2c83`
真实 `exit 1`：Ruff 和环境声明通过，Pyright 全树 ratchet
新增唯一错误 `engine.py: Code is too complex to analyze`，
未进入全量 pytest。**绝不把此轮当 R9 PASS。**

已将内联 pre-send 守卫机械抽取到现有
`engine_services/observation_visibility.py`，引擎只保留委托和
`run_incomplete` 收口；不增加新 ledger、模型配置或工具重放。
修订后专项 `212 passed`、全树 Pyright ratchet
`new=0/changed_file_diagnostics=0/PASS`、Ruff PASS。
补齐 guard 自身异常的 fail-closed 负向测试。

回执：
`docs/governance/receipts/RECEIPT-20261114-local-model-repetition-R9-first-fail.json`、
`docs/governance/receipts/RECEIPT-20261114-local-model-repetition-stage1-refactor-GREEN.json`。

**代码 SHA 已变化：前一轮独立 Reviewer PASS 不继承。**
须冻结新代码候选、重新独立 GLM-5.3 审查，
PASS/P0=P1=0 后重新原版完整 R9。


## 第二次独立审查：REVISE / P0=0、P1=2、P2=3

Pyright 复杂度补修后的候选 `ea736919a786b89ae8cc5ed816b43d7cbf061364`
已由**新的** GLM-5.3 独立 Reviewer 单次真实调用、零工具、
合法 JSON、精确 SHA 验证，正式裁决 **REVISE**。

- P1-1：原测试回执绑定的是补修前 base，不是 `ea736`。现已在
  `ea736` 精确 Git tree 上重新执行 `212 passed` 和全树 Pyright
  `new=0/PASS`，逐文件 Git blob OID、文件 SHA 和日志 SHA
  记录于 `RECEIPT-20261114-local-model-repetition-ea736-exact-tests.json`。
  这只解决证据绑定，**不改写 Reviewer 原始 P1 计数**。
- P1-2：尚未实现 owner/version/paging 资格化且最终模型可见的
  `evidence://` exact-ref 交付。当前实现对无法容纳原文的合法 Evidence
  仍可能 HOLD。必须在下一隔离补修批次实现最小精确恢复，
  或经独立审查认可的配置级临时隔离门；**当前候选不得上线**。
- P2：不完整工具组诊断、结构化 provider_sent 字段、
  重建后的缓存前缀/epoch 对账，待专项补强。

正式 Reviewer 回执：
`docs/governance/receipts/RECEIPT-20261114-local-model-repetition-stage1-refactor-GLM53-REVISE.json`。

**门禁**：独立代码审查非 PASS，故不运行下一次原版完整 R9，
不合并 main、不 push、不发布、不重启。旧 M4-C 债务仍 HOLD。


## exact-ref 最小恢复接线（隔离候选，待独立审查）

在现有 `observation_visibility.py` 内完成最小
`read_evidence` 精确恢复投影：验证 Provider 当前可调用工具 schema、
注册的真实 EvidenceReadTool、OwnerScope、EvidenceRecord 工具调用绑定、
版本 token、FILE freshness、BlobStore 有界分页及 SHA 完整性，
再将当前同 Run 原子工具组投影为 JSON 事实 capsule。
不重执行源工具，不暴露 workspace/session 身份，跨 owner、
缺工具、过期来源、缺版本、坏 blob、超物理预算均 fail-closed。

原始 exact-ref RED `1 failed/2 passed` 现为 GREEN；
新增正负向后 **225 passed**，Ruff PASS，
全树 Pyright ratchet `new=0/PASS`。
真实 LoopEngine + FakeLLM + EvidenceEnforcer + EvidenceReadTool
在 101 个 schema、可用物理预算下完成第二轮，
Provider 可见 `evidence://`，并可按 4000 字符分页恢复原文。

**严格边界**：当事故 `28,659` schema tokens + `32,768` 输出预留
只余 `3,698` 字符时，现有完整 system+ingress+ref capsule
仍可能无法放入保守物理预算；此时必须 HOLD，不得伪装已交付。
后续若要提高此情形完成率，需独立验证工具 schema
按需缩减/index-only 或实际 tokenizer 预算，不能随意改模型配置。

GLM-5.3 开发代理此次 exact-ref 补丁输出截断，未被应用；
由验收方最小实现，**必须交新的独立 GLM-5.3 Reviewer**。
测试/代码身份回执：
`docs/governance/receipts/RECEIPT-20261114-local-model-repetition-exact-ref-GREEN.json`。


## R9 第二次阻断：架构棘轮三项（已按官方口径修复）

原版 R9 对 exact-ref 候选 `97ac7665bc06870811fd91a935c6a295708313ae`
真实 `exit 1`，Tier0 `338 passed / 2 skipped / 3 failed`：
① `engine._run_stream_inner` AST 长度超登记；
② 两个新 helper ≥120 行未登记；
③ engine 函数内 import 增长。**未进入完整 R9。**

已把新增 import 移到模块顶层，使用仓库官方
`scripts/regen_function_size_baseline.py` 并执行 `--check` 幂等验证；
engine 新登记 `2215`，两个 helper `174/144` 精确登记，
同时收紧六项旧登记，未修改 arch guard 断言或降低门禁。
原三项失败定向复测 `3 passed`；
合并定向 `228 passed`，Ruff PASS、全树 Pyright ratchet PASS。

正式回执：
`docs/governance/receipts/RECEIPT-20261114-local-model-repetition-arch-ratchet-fix.json`。

**候选源码已变化，须重新独立 Reviewer PASS 后再原版完整 R9**；
不可继承上一候选 PASS。


## 架构补修独立审查：正式 PASS

冻结候选 `a291a05da0e6f0229040294ed193d5b556df7be9`
由新建独立 GLM-5.3 Reviewer 完成单次真实审查、零工具，
`finish_reason=stop`、`truncated=false`，合法 JSON，
精确 HEAD/diff SHA 校验通过。**PASS，P0=0/P1=0/P2=1，
AC1–AC10 全部 PASS**。

唯一 P2 是后续应进一步拆分 `_run_stream_inner`
巨型函数，减少架构债；本批已用官方重登记显式披露
`2192→2215` 的新增行数，不隐匿放宽，不修改守卫断言。

正式回执：
`docs/governance/receipts/RECEIPT-20261114-local-model-repetition-arch-fix-GLM53-PASS.json`。

当前其他 M5F Goal 正独占运行原版 R9；本 Goal 待其退出后
再运行原版完整 `bash scripts/ci_gate.sh`。设计/代码 Reviewer PASS
**不能代替 R9 exit 0 或生产验收**。


## 原版完整 R9：真实 PASS / exit 0

对隔离候选 `5acc085ea59c7b66fb7bd2dddb96bf505d752fea`
原样执行 `bash scripts/ci_gate.sh`，真实 `exit 0`。
该候选 `src/tests` Git tree 与独立 GLM-5.3 Reviewer
PASS 的 `a291a05da0e6f0229040294ed193d5b556df7be9`
逐字节相同；仅文档回执增加。

- Ruff 全树 ratchet PASS；Pyright 全树 ratchet PASS；
  env-pin PASS。
- Vitest：`57 files / 600 tests` 全通过。
- Tier0 `341 passed/2 skipped`；Tier1 `7 passed/2 skipped`；
  Tier2 `3 passed/2 skipped`。
- 原版完整 pytest：`15,023 passed / 158 skipped / 3 xfailed`；
  serial_signal `1 passed`。
- 未与其他 Goal 并发 R9。

正式回执：
`docs/governance/receipts/RECEIPT-20261114-local-model-repetition-original-R9-PASS.json`。

**下一门禁**：受审查隔离分支 push → GitHub 远端 CI/精确 SHA →
保护现有脏 main 和其他 Goal 工作树后再考虑集成。
此 R9 PASS 不证明历史 Ornith-MLX 模型身份，也不证明
事故 `3698` 字符预算下每次都可恢复；未经生产资格化
不得发布或重启。
