# RESULT — Rule28 × Jev 专项修复收敛，受控 Web-only 上线资格

日期：2026-10-15。**收敛开发资格 PASS；未合并 main、未上线、未获得用户的生产授权。**

## 1. 最终运行时 Jev 实现权威与并行状态

- 采用 Jev 专项 Agent 本地已提交的 `c0f577d181bb677109b7ced2b3474a5b1e87eedf`，2 文件原始冻结 diff SHA-256 `b31c73f5d8da7d5d001253c10414e59801b1a60b1eeb858bfeb1924a913ed331`。本收敛分支 `fix/rule28-jev-converged-20261015` 的 `src/llm_loop/knowledge/jev/wire.py` Git blob **`32a1d4c41d4c26acddce07b21fcbbb0e54ad4d92`** 与专项提交相同（逐字节一致）；最终不保留旧 Rule28 分支额外的数值过滤投影。
- 原始 Rule28 除 Jev 之外 24 文件（包括 2026-10-08 fixture clock 修复和 browser 测试动态端口修复）与该 Jev 专项 2 文件在**新独立树**拼合，不覆盖 Jev/Rule31 各自工作树。再补 4 个非数值概率参数化测试。
- Jev 专项独立 R9 结果仍如实保留：**8,850 passed / 146 skipped / 2 failed**，失败原因是日期漂移和固定端口测试；本收敛候选同时包含这两项测试修复，但**不声称专项旧分支自身绿**。
- 附加真实离线对照：原 Rule28 版 Jev 和专项 Jev 的 **1,550 组 choice/score** 测试输入相同输出，差异 0、Provider 调用 0。完整数据 `data/rule28-jev-convergence/semantic-differential.json`，SHA-256 `bddfeb60234535a7d7277ac07159e6ef43823e792630dd91980fa3d851bd9b7e`；这是有界测试事实，不是形式化等价证明。

## 2. 联合源码与独立 Reviewer 准入

- 基线已提交 main `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`，最终在分支 `fix/rule28-jev-converged-20261015` 隔离源码提交 `604592a243080bc4bb366853764992114605840b`（26 文件）。完整 `git diff HEAD^ HEAD --binary` SHA-256 `dced89e9733fb289cfbdea0d04407d6da9041fbb6358ddb27b598da2d054af0f`，**170,445 bytes**，与 Reviewer 输入逐字节一致。
- 真 GLM-5.3 只读子代理 `subagent_0c925ea1b114`，真实唯一 EventStore terminal `836cb723-09b2-46df-ba53-bd208a0dda4a`、隔离 completed 进程内结果有效；机器资格 **PASS，P0=0，P1=0，P2=3**。原始 JSON `data/rule28-jev-convergence/glm-child-review.json`，SHA-256 `76c484f60386ee9255ac788f1dd90f1cfe5ed4aae2a0d88af3e4ff333c423c15`。
- 非阻断 P2：不可达重复 return；离线测试无 EventStore 时审计可见性；计数解析偏保守可能误拒。未冒充这些改进已落地，也未用旧审核资格代替新 SHA 复审。
- 新候选联合定向 **409 passed**，包括 Jev、Knowledge、Rule28 Host/Browser/SubAgent 及原两项日期/端口测试。

## 3. 原生项目完整 R9

- 对最终源码 SHA，经独立 Review PASS 与无并发全量 CI 准入后，实际执行 **原版 `bash scripts/ci_gate.sh`、exit 0**；随后另一个 Agent 启动 quick 门禁，并未修改本冻结补丁。
- Ruff PASS、Pyright PASS、Env-pin 862 文件 PASS、WebUI candidate build；Tier0 **319 passed / 8802 deselected**；4-worker xdist **8,959 passed / 146 skipped / 13 warnings**，无失败、无需 serial 降级；guard report PASS。
- 原始 R9 `data/rule28-jev-convergence/native-full-r9.log`，SHA-256 **`2a011bfd01f071fdb3690e1ea4a52f2b24cdb6a9feeef459697063a7ba7d1c10`**；最终源码提交 diff SHA 不变。
- R9 自生成 18 份 tracked phase3–6 报告变更；先白名单验明、封存二进制差异到 `data/rule28-jev-convergence/r9-generated-reports.patch`（SHA-256 `15ed0b28361af33e4ac70ac9ae7e6e4ab62e5dba54088c8a3f9aa364dc4933b6`），再只恢复这些报告。没有重置他人的并行目录或主仓库。

## 4. 生产与能力边界

- 至最后读取，Web/Feishu/Learning live manifests 都绑定 `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`，并非本候选；尚未 merge main、push、deploy、restart。
- 限定范围：仅目前已识别的 `execute_command` 高风险 full-test/push 入口与有文稿编辑器证据的明确 Publish click；Host 准入和独立 Reviewer 之外还需原有用户授权/服务权限。
- DSH 下游进程、任意动态 shell 包装、模糊 Submit/Enter/HTTP/CDP/外部 API 发布不具备全覆盖保证，故**全域三闸生产结论仍为 NO-GO**，不应通过过度禁止正常 Agent 工具来制造虚假百分百覆盖。

## 5. 待批准的 Web-only canary

详细申请见 `docs/governance/requests/REQUEST-20261015-rule28-limited-web-only-canary.md`。申请的是**限定范围、单次受控操作**，不是长期放权：最新 main 冻结与最终合并树复审及原版 R9，检查活跃会话和服务身份、Web-only 受控发布与重启、私密/模拟的正反测试、异常回滚；**不 push、不重启 Feishu/Learning、不真实远端推送、不公开发表文章**。如资格丢失、in-flight 未安全收敛或无法回滚即停止。**本轮仅提出申请，没有执行。**
