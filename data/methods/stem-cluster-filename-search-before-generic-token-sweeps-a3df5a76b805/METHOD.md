---
method_id: stem-cluster-filename-search-before-generic-token-sweeps-a3df5a76b805
name: stem-cluster-filename-search-before-generic-token-sweeps
description: 当修复目标已可具名（本集为 attestation 的 argv 解析）时，先用词根做文件名级检索一次拿到完整制品簇（源码/单测/S4 文档/S0 探针，5/5 全相关）；通用 token（cmdline/shlex）的全库内容检索只回答“字符串在哪”，且命中被 .venv/site-packages vendored 树占满 30 条截断窗口——回执中 vendored 占多数即“仪器选错”的机械信号，应切换仪器而非第三轮换词。簇内文件读取一律逐字复制回执路径（本集两次 path 失败均因凭记忆重造日期/前缀）；内容检索只保留给簇内影响面确认。搜索空间从 90+ 条截断命中缩到 5 条全覆盖簇。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:43696f9c-0fd9-4c30-b4d9-3f05343cba9a:147:2519360007ac35521b36
evidence_refs: learning:learn:93231334e371
created_at: 2026-10-06T02:26:40.025966+08:00
updated_at: 2026-10-06T02:26:40.025966+08:00
---
## Trigger
任务要修改一个已具名的机制/模块，需定位其源码/测试/文档簇；或同一全库内容搜索 source class 连续换 token，命中被第三方/vendored 路径占据截断窗口。

## Discriminator
首个内容搜索命中已给出机制词根与文件族（*attestation* 测试与 S0 文档）；修复的未知量是“哪个文件实现它”，文件名级检索可直接回答（后续 5/5 全相关），而 cmdline/shlex 换词扫描的回执自身演示了 vendored 噪声占窗。且失败读取的正确字符串当时已在先前回执中显示：docs/S4-RESULT-20261006-…（第 4 步文件名检索原样列出，读取却用了不存在的 20260906 日期）；src/ 前缀惯例可由同簇既有成功读取（src/llm_loop/...）归一，不必凭记忆重构。

## Short path
- 从已知失败 token 提取词根（attestation），文件名级检索获取完整制品簇：attestation.py、单测、S4 结果文档、S0 探针脚本
- 簇内读取逐字复制回执路径；显示路径缺 src/ 前缀时以同簇命中/既有成功读取的前缀归一，不凭记忆重构日期或目录
- 先读权威记录（S4 doc）确认失败机制与约束，再读源码定位解析点（_ps_argv + shlex）
- 影响面用限定内容检索确认（_ps_argv 使用者、attestation.json 消费方），不另起全库换词扫描
- 修改 → 单测 → 探针正负向复核全绿即停止

## Stop conditions
- 文件名检索的簇已覆盖 source/test/doc/tooling 且条条与词根相关：停止发现，转入阅读与修改
- 内容检索命中被 site-packages/_vendor 占据截断窗口：立即切换为限定路径或文件名级检索，不再第三轮换词
- 原失败场景复核变绿、安全负例仍 fail-closed、回归不退化：修复闭环，停止

## Verification
- 检索质量机械检查：结果中 vendored/第三方路径占比高 ⇒ 仪器选错
- 每次 read 的路径与最近回执展示字符串逐字符比对；不一致即停，改用回执原样路径或按同簇前缀归一
- 修复后必含一组原失败用例复现 + 一个安全方向负例（本集：含空格 dedicated profile 放行，且授权树内含空格 profile 仍拒绑）

## Counterexamples
- 症状驱动且无任何具名线索（如“测试偶发失败”）：只能由特征 token 内容搜索起步，本方法不适用
- token 对业务代码足够独特（如只有源码会出现的报错串）：内容搜索本身就是窄仪器，无需词根簇定位
- 目标是枚举某通用 API 的全部 callsite：全库内容检索正是目的，应按 method-repo-api-discovery 一次查证
- 回执登记路径已失效且文件可能刚创建：需按回执提示重新 read/再定位，不得盲信旧回执字符串
