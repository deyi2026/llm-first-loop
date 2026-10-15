# 2026-10-15 Rule28 最新 main 集成验收回执

**状态：隔离源码提交完成；真实独立 Reviewer PASS；canonical R9 exit 0（xdist 单例红后串行通过）；未合并 main，未生产发布。**

## 一、范围与候选身份

- 最新 main 基线：`db4aaa8565ea0d0cc061b12e5701f5398b53698e`，本任务期间 main 不动。
- 工作树/分支：`.worktrees/rule28-main-gates-20261015` / `fix/rule28-main-gates-20261015`。
- 已审源码提交：`24a99fa266e068dfe9c1bab796e2b6e49b48d116`，14 文件，185 insertions / 60 deletions。
- `git show --format= --binary HEAD` 的完整 SHA-256：`2b18adc7736a6d09082be35e3c22e8ca1be0840a12bbd701264e02eb810bdd7b`（原独立 Reviewer 所读 staged patch 同一字节）。
- 目标仅是 Rule28 强制前置**行为义务与提示/观测真实性**，不把模型声明或工具中 PASS 文字冒充 Host 准入。保留现有 Rule29/31/32/33 及其他 main 实现。
- Rule28 回执仍为 observation，`review_qualification_verified=False` 是诚实边界，**没有真正程序拦截所有 shell / 发布入口**。此次不得当作 P0-B 已完成。

## 二、真实独立 Reviewer

- LFL 原生 `SubAgentRunner` 使用独立 EventStore(enabled=True)、独立会话、零工具白名单；Reviewer 模型：`glm/glm-5.3`（one-shot low-effort）。
- 真实 child：`subagent_139802203744`；唯一 `subagent.terminal` 事件：`d80969a1-676a-48a7-b107-39c909b5ea1e`，state `completed`。
- VERDICT: **PASS**；P0=0 / P1=0 / P2=3。被审补丁 SHA 精确匹配。完整模型输出与身份元数据见 `docs/governance/receipts/RECEIPT-20261015-rule28-main-glm53-independent-review.json`。
- P2 留后续：Rule28 SoT 例外称“文章闸”而标题改“文稿闸”；浏览器无关动作仍看到条件文稿审查提示可能带来 compact 字符额外开销；临时端口 `lsof` 校验在其他 OS 的行为仍未交叉验证。P2 未解除或跳过任一真实安全/代码门。
- 早期尝试分别暴露了隔离测试启动器 .env 行内注释解析问题、Provider 8k 输出全耗于推理未得终答、单一 Reviewer 报告计数自相矛盾等；失败回执保存在 ignored runtime，任何一次未合格的 PASS 文本均未放行全量测试。

## 三、R9 真实验收（项目原生脚本，不降门槛）

- 50 focused regression passed；先前曾受 OS 外层 sandbox 干扰的 5 个邻接测试文件在本隔离工作树内 `46 passed / 1 warning`。
- `bash scripts/ci_gate.sh` 真正最终 **exit 0**；Ruff PASS、env-pin PASS、Pyright PASS（new=0, touched diagnostics=0）、WebUI 从候选源码构建 PASS。
- tier0：**319 passed / 8588 deselected / 3 warnings**。
- xdist 全量：**8744 passed / 1 failed / 146 skipped / 13 warnings**；唯一失败：`tests/phase6/test_m1_sync_interrupt.py::test_s4_multiple_interjections_all_consumed`。
- CI 内置 D-B2-09 原有降级核验：该**同一个测试文件** serial 复核 **9 passed / 1 warning**，ci_gate 如实标为“xdist 分布假红（不阻断）”；不能宣称 xdist 完全无红、或失败测试被删除/跳过。
- full R9 原始日志（ignored runtime `data/rule28-r9-guard/canonical-r9.log`）SHA-256：`f8d6e9ba1ad913150d80ac346908d8c7648ef72660ba9c7355a94fb8d92a1b1a`。
- 只在 pytest 子解释器启用临时 Python `sitecustomize` 非回环网络拒绝守卫，预先单独自测本地 loopback/AF_UNIX、远端 TCP/DNS 拒绝、全新 httpx trust_env=False 及 child 继承；OS 顶层不额外包 sandbox，以免套娃导致 lsof/Unix Socket/Chromium 假红。凭据环境变量从 CI 进程显式 unset、隔离工作树无 `.env`。**这是 Python 级守卫，不是全进程物理出网封锁**；不能用其证明任意非 Python 子进程绝对不出网，真实 Provider 审查调用与离线 CI 是两种不同阶段。

## 四、测试副作用和 Git 证据

- 全量开始前仅 14 staged files，tracked unstaged 空；测试结束后精确识别 18 份 `reports/` 下自动更新的 tracked 报告。保存其原始差异（ignored `data/rule28-r9-guard/canonical-r9-report-side-effects.patch`）SHA-256：`eb2d238c7b190f603d31d1e2a9a0d02ca265b9ca66ca427fa100381a0e54a5ec`；只对这 18 条白名单文件进行 `git restore --worktree`，未清理其他 worktree/Agent 文件或 untracked 产物。
- 再次校验 cached diff SHA 与原独立 Reviewer 完全一致，`git diff --cached --check`、14 文件 staged 安全扫描和 pre-commit 安全扫描均 PASS；源码提交后 tracked worktree 清洁。
- main/其他分支没有被合并、reset、push。生产 Web/Feishu/Learning 没有被部署、重启或切换新 Rule28 源码。

## 五、真实剩余边界与后续工作

1. **P0-B 未完成**：三个真实动作入口的 Host 可核验独立子代理 PASS、动作类别、候选 SHA、remote/ref 或文章目标、父/子身份、窄复审覆盖、授权分离；无回执时动作绝无副作用；必须核验真实入口的漏触发/误拦截，不能仅靠文本字符串匹配。
2. **P1 未完成**：Rule29 用后负反馈必须在任务收口前留下完成或未完成回执；Rule31 不适用与错误引导的分路处置、净分未验证 applied=+1 口径缺陷、已闭环卡片的新证据再触发。
3. **P2 未完成**：Rule24/27/32 的真实触发定向审计。
4. 当本轮任务进入下一阶段时先在干净的新候选完成上述内容，必须重新独立代码审查/完整 R9；是否 main 合并和运行态生效须另核 in-flight 会话、Release 资格与控制面，不得把本次隔离通过等同生产上线。

**结论：Rule28 强制审查义务已在最新 main 基线的隔离源码中验收并单独提交，但真实三闸 Host 强制阻断和生产生效还没有实现。**
