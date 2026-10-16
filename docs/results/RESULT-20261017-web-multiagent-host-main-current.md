# RESULT — Web Multi-Agent Host 准入适配（重基于最新 main 的独立验证收口）

- Goal: GOAL-20261016-bd8d4d65（独立 Goal，不触碰其他会话/LFLM MCP Console 的「安装分发与生态提升」）
- Worktree/branch: `.worktrees/web-multiagent-host-main-current-20261016` / `fix/web-multiagent-host-main-current-20261016-current`
- 基线 main: `8041dc357d0c7ed75ed92ca5d4fad816342aa46d`
- 代码候选 commit: `8634db468`（cherry-pick e6a0fdda5+963847000 十文件 + 本会话语义加固）
- 预提交 staged diff SHA256: `0834145b2c3df15c14242a10f7383317e53abba1fd32be79386e4fb681a9597b`

## 1. 与 main 交叉修改的语义兼容结论（不只 Git 无冲突）

main 在原基线 c3c306f6d 后由 `527fe6463`/`fef342164` 引入两处交叉：

1. `spawn_subagent.py` 新增 `requires.fs_isolation` 透传；候选 patch 同时改了同一处 `required_tools` 归并逻辑。合并后语义：仅显式 `"tools" in requires_raw` 才传列表——`{"tools": []}` 现在产生硬零工具 child（`required_tools=[]`），未声明仍为 `None`（继承默认 scope，不含 spawn_subagent 防递归）。方向为只降不升，且有 `test_spawn_tool_preserves_explicit_empty_vs_omitted_tools_without_provider` 钉住三种形态。
2. `runner.py` 新增 `fs_isolation` worktree 施工面（prepare 失败即拒绝、绝不降级共享工作区）。**发现的真实缺口**：canary 拒绝条件未覆盖该新轴——canary root 理论上可为 child 声明 fs_isolation，购买共享 ledger 无法记账的物理 worktree 资源。修复：runner 拒绝条件纳入 `fs_isolation`（RED→GREEN：`test_runner_refuses_canary_child_fs_isolation_request` 修复前失败、修复后通过），dispatch 层 parametrize 扩展（`requires={"tools":[],"fs_isolation":True}` 拒绝）双保险。

## 2. 本会话新增测试（Provider-free RED/GREEN + 负向范围）

`tests/unit/test_web_direct_subagent_canary.py` 34 个用例（原 29 + 新增）：

- dispatch 层 fs_isolation 声明拒绝（parametrize 扩展）
- 取消按会话+generation 范围：`cancel_parent("foreign-session", correct-generation) == 0`
- UNKNOWN attempt（interrupted）保留负债并拒绝重试；成功 attempt 全额计费但允许下一轮（8 次上限内）
- runner 层 fs_isolation 拒绝（RED→GREEN）
- 恢复：新 store 实例重载 ledger 后伪造第二子 `subagent_canary_member_not_authorized`；停止后重建句柄的迟到 attempt 被 `budget_not_active`（磁盘 ledger 相位而非内存闩）封锁

## 3. 验证链（全部真实物理退出码）

- targeted：`pytest` 三文件 → 90 passed
- 静态：ruff / pyright（触碰文件）→ 0 错误
- Quick：`bash scripts/ci_gate.sh --quick` → exit 0（tier0 319 passed）
- 独立审查：review_admission（GLM-5.3，零工具、不继承）→ 见 `4 分层
- 原版 R9：`bash scripts/ci_gate.sh` → exit 0；xdist 全量 **9201 passed / 141 skipped / 0 failed**（182.18s），无需 D-B2-09 串行复核

## 4. 独立审查的诚实分层（关键）

- 4 次审查子代理中 3 次死于 `LLMEmptyResponseError`（思考 69-70k 字符后空响应，glm-5.3 长材料瞬态；child: d332475b/d9ecaa89/7e89963b）。
- `subagent_d70044fe0589` 完成**完整代码审查**（tokens_in 18490）：正文覆盖 profile/store/dispatch/runner/web 层、旧 profile 不变、测试钉住；verdict 块被 16000-token 输出上限截断；有界续话补发 verdict：**PASS，P0=0，P1=0，P2=4**（均为维护性备注），并复核冻结树 SHA `962d3760…07314` 一致。续话结算使该 child 失去 Host 活体证明，无法签发正式资格。
- 按已验证方法（EXPERIENCE-20261016-rule28，用户确认上下文过长假设）：已审大头本地 commit（`8634db468`，本地提交不触发三闸），留 2.2KB 登记残留；`subagent_7ed056917fac` 对残留材料一次通过，Host 签发正式 full_test 资格（candidate `0826d178…`）。
- **声明边界**：正式门禁 PASS 覆盖残留登记材料；代码审查 PASS verdict 覆盖代码树。两层分别记录，不互相冒充。

## 5. 未做（明确越界，需另行授权）

生产 Provider Canary、本地 main 合并、push、发布、重启、三层递归委派、扩大 Host 权限。Stage A/B 双层委派验证见 CANARY-LAUNCH-MATERIALS 文档，待显式授权后执行。

## 6. 产物索引

- 回执：`docs/governance/receipts/RECEIPT-20261017-web-multiagent-host-main-current-rule28.json` 与 `...-r9.json`
- 登记：`docs/governance/rule28-admission-registration-web-multiagent-host-current.json`
- 上线材料：`docs/governance/CANARY-LAUNCH-MATERIALS-20261017-web-multiagent-host.md`
