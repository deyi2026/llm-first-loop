# 事后审查回执：cc94ac81b（内容审查，非推送准入）

- schema: lfl-posthoc-review/v1
- 对象: cc94ac81bfee27f8b71ea4b17f2649be2545fd62（父 e915bdb134d5a4a88015ba139745de8becc818fb）
- 补丁: tmp/posthoc-cc94ac81b/cc94ac81b.patch，406 行，sha256 482141fe6f7b503682457fe1ded74f9069de5ce49b0b7e98afc1a21aa963a565
- 性质: 已推送后补做的内容审查。**未签发 review_admission 推送资格**；不证明推送方执行环境。
- 审查者: 主模型 + 独立只读子代理 subagent_8c3a745be05b（其结论 REVISE，逐条裁决见 §3）

## 1. 事实

- delta 为单提交 8 文件 +187/−26：`.github/workflows/ci.yml`、`pyproject.toml`、`uv.lock`、`scripts/ci_gate.sh`、4 个测试文件。
- 到达本机路径：`git fetch` fast-forward（refs/remotes/origin/main@{3}），作者 `MCP Console <mcp-console@users.noreply.invalid>`。本机未执行该推送。
- `data/review_admission/`（81 条记录）中引用 cc94ac81b / 等价本地提交 f391d1ba1：**0 条**。
- CI run 42924222973（main 分支）= **failure**：6 条 FAILED，红数对账报 1 条 `[NEW-RED] tests/unit/test_review_gate::test_execute_command_full_test_receipt_carries_gate`，`[GATE] 红数对账 = FAIL` → 阻断。即门禁在该提交上 fail-closed 生效，未放行。
- 前序 run 42854325411（e915bdb13）= failure，红项为 jsonschema 缺失、sandbox-exec 不可用、installer systemd 前置、escalation 属主权限、smc typed wait 真时钟 —— 正是本提交针对性修复的对象。
- 余红由后续 `91d15c230`、`50431d350` 修复；自 02:29（a96e1c3d7）起 main 连续 3 次 success（至 fcfb40270）。
- 现行 `eval/rules/known_reds_current.json` `registered: []` —— 无白名单在起作用。

## 2. 门禁面核对（本提交是否放宽）

- CI 由 ruff/pyright/pytest 三条独立步骤改为调用完整 `scripts/ci_gate.sh`：选择集由「全部 minus real_llm/serial_signal」扩为 tier0 + serial_signal + serial_perf + 并行全集，且空选集 exit 5 阻断。**覆盖增加，非减少。**
- `tee` 吞失败风险：实测日志显示 CI shell 为 `bash --noprofile --norc -e -o pipefail`，管道失败可传播。**不成立。**
- `[4/5]` 隔离 HOME + 候选 WebUI 构建在 CI 中 9s 完成，`[5/5]` 全量跑完才在红数对账处阻断 → `npm ci --ignore-scripts` + build 路径在实测中可用。
- `tests/test_sandbox_scope_roots.py`：删 3 处 skipif，改 stub `_sandbox_exec_applicable`；模块内 autouse `_fresh_auto_cache` 重置 auto 缓存；argv 断言保留。
- `tests/unit/test_linux_installer_scripts.py`：新增 fake `systemctl`（`--user show-environment` 失败）并断言安装器打印降级提示且只调用一次 —— **加固**，非跳过。
- `tests/unit/test_smc_browser_typed_wait_v06.py`：真时钟换假时钟，保留 `timeout_ms=1` 与 satisfied/indeterminate 双断言。
- 8 文件无 `src/` 变更；无权限/隔离逻辑改动。

## 3. 独立意见与裁决

| 编号 | 主张 | 裁决 |
|---|---|---|
| P1-1 | CI 继承 xdist 抖动复跑放行（serial 绿 + 并行复跑绿 → exit 0，仅打印告警） | **保留 P1（暴露面）**。机制在 e915bdb13 已存在，非本提交新增；本提交把 CI 判定从裸 pytest 切到该机制，抖动从此可通过 CI。建议 CI 侧加严格开关，或至少把首轮红文件清单落 artifact。 |
| P2-1 | `tee` 退出码依赖平台默认 pipefail | **关闭**。实测日志已证实 pipefail 生效；仅作未来重构提示。 |
| P2-2 | 依赖预检把「venv 缺失」与「依赖缺失」并入同一条消息 | 接受，P2。 |
| P2-3 | 假时钟 patch 模块级 `time`，同进程其他线程/插件计时同被冻结 | 接受，P2。 |
| P2-4 | stub 私有函数，改名/改调用后桩静默失效 | 接受，P2。 |
| P2-5 | pyright 墙钟超限 exit 0、结论行只二分 complete/unknown | 非本提交引入，P2 观察。 |

## 4. 残余与不可证

- 只能审内容，不能证明推送方执行环境与所推树一致；作者身份为占位域。
- 未在本地复跑该提交全量门（CI 已给出结论；本地复跑需独立 worktree 与全量门通道）。
- `uv.lock` 中 `attrs` 等间接依赖未逐行核对，仅核 jsonschema 及其传递依赖入 lock。

## 5. 建议动作

1. 内容层面无 P0，不需回滚。
2. P1-1 单独立小改动：CI 侧关闭抖动复跑放行（或失败清单落 artifact）。
3. 本回执如要入库，走 lane + 合并审查（RULE-AI-34/28）；当前为未提交文件。
