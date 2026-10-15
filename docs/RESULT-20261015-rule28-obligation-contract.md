# RULE-AI-28 前置审查义务与观测契约修订

日期：2026-10-15；状态：完整独立代码审查及窄复审均 PASS；第二次完整 R9 exit 0；已在隔离分支固化源码。首次失败原样记录。

## 授权与范围

用户在核查“只提醒不阻断”是否削弱规则后，确认按建议执行。本轮落实最近确认的规则措辞、父 agent 责任、工具调用前可见提示及观测证据的诚实标注。

代码全量测试、所有对外发表文稿、任何 git push 仍须对应专门独立子代理审核 PASS。程序不替模型作专业审查，不因日志故障或普通 PASS 文本授予资格。泛化的继续、按建议执行、授权发布均不是免审。

本轮不把文字修改表述为通用程序强制准入已完成；未新增通用 shell 解析控制器或浏览器发布意图分类器。

## 候选身份

- 基线：2ad0bc06d55aefa3496bdf8c26bad1a4dc2963b2。
- 分支：fix/review-prerequisite-20261015。
- 已审源码提交：0a92fff22983df5aad931ca48a9b8573dda0e66c；提交差异 SHA 与最终受审补丁一致。
- 初审 source patch：git diff --cached --binary，13 文件，42,375 bytes。
- 初审 SHA-256：e290e364af284f6d711d2dd9f40c4689f5e9fa5453d13e81412a9e3c1984c56c。
- 最终候选：14 文件 / 43,753 bytes，SHA-256 ae5b285c114362227ffe1a3b826fc0df180dedbce23e50f75ec815d0de7980a7。
- 本报告与原始独立审查回执单独归档，不冒充受审 source patch。

## 修改

1. RULE-AI-28 明确“强制前置义务”，由父 agent 主动安排未参与产出的专门 reviewer；未完成或失效时暂缓对应动作，继续可推进工作。
2. 文稿范围覆盖所有对外发表文稿；三个审查 skill 同步义务、真实子会话、产物指纹、窄复审覆盖关系和明确免审边界。
3. shell 与两个浏览器操作工具的 Full/Compact 描述在调用前展示条件义务；不改 universal system prompt、参数、工具可用面或执行策略。
4. VERDICT/JSON 仅作为未核验的工具文本线索；review_qualification_verified 固定为 false，移除自声明审查资格位，不称文本匹配为有效回执。
5. service_control publish 标明代码部署，不能作为文稿发表入口或发表资格。

## 验证

- 新增 5 项规则/工具契约回归：修改前 5 failed，修改后通过。
- focused（新契约、review gate、规则分离、common governance）：31 passed。
- adjacent（含 schema_lazy、Browser、service_control、registry）：56 passed。与 focused 有重叠，不相加。
- compact shell 提示初版触发现有体积断言；压缩措辞后通过，未放宽测试阈值。
- canonical quick：exit 0；Ruff/Pyright/env-pin/WebUI 构建通过；319 tier0 passed。
- staged security scan：13 文件 PASS；diff check PASS。
- 独立代码审核：/root/rule28_independent_code_reviewer，PASS，P0/P1/P2 均 0；独立复跑 21 passed；受审 SHA 与文件数如上，原始回执单独保留。
- 首次完整 R9：原独立 PASS 回执落盘后才启动；exit 1，14 failed / 8722 passed / 146 skipped / 4 errors，serial 14 failed / 49 passed / 4 errors。执行方额外外层 sandbox 与嵌套 sandbox、AF_UNIX 和 Chromium 不兼容，此次红不得算代码通过。
- 同 5 失败文件在无 Provider 凭据的清洁环境、无额外外层 sandbox 下复核：66 passed / 1 failed。剩余为既有固定端口 39099 实际被本机其他应用占用，测试的无监听前提不成立；原 test 与 attestation.py 与基线字节一致，未操作占用端口的应用。
- 最小测试修复：第 14 文件 tests/unit/test_browser_attestation_v01.py 改用 OS 分配并保留但不 listen 的 socket，真实 lsof 路径与原两个断言不变；同 5 文件再核 67 passed / 4.16s，Ruff/security scan14/diff check通过。
- 最终候选：14 文件 / 43,753 bytes，SHA256 ae5b285c114362227ffe1a3b826fc0df180dedbce23e50f75ec815d0de7980a7；原13文件patch SHA e290e364...c56c完全不变。第14文件另修两处既有 import 诊断以满足 touched-file 零诊断，未全文件 format；独立窄复审 PASS / P0=P1=P2=0，真实单节点 1 passed / 0.08s。
- 第二次完整 R9 在窄复审回执落盘后启动：环境仅传基本 OS 变量，不带 Provider 凭据，工作树无 .env，保留项目自带测试隔离和原生沙箱；不套额外外层 sandbox，不减少测试选择。最终 exit 0：8740 passed / 146 skipped / 13 warnings，193.59s；xdist 全量绿，无 serial fallback。另有 tier0 319 passed、架构 guard_report 1 passed / 29 deselected，Ruff/Pyright/env-pin/WebUI build 全通过。
- 首次测试生成18个tracked reports，已在记录其diff SHA256 02a7f18bde6de644dbab53e90352e387fe8bf7ced6a828f44c081d041c534933 后按精确路径白名单恢复，未恢复其他文件。

## 实现覆盖与后续验收

本轮实现规则义务和调用前 schema 提示；工具返回里的提示仍是观测说明，不是自动准入裁决。真实子会话归属、独立性、产物/目标一致性的通用程序核验，以及所有 shell 包装、标准全量脚本、平台发表入口的强制覆盖尚未在本轮实现。原形态分类器的漏检/误报也未在本轮改写，不能声称已经修复。

后续若实现动作准入，须用实际副作用为零、真实回执及产物/目标绑定、窄复审覆盖、只读/定向检查不受误伤等验收；不能仅以提示在场或单测绿宣称规则在所有生产入口强制生效。

本轮不合并 main、不 push、不发布或重启；主工作树其他任务的修改不动。运行服务加载版本未验证，本报告不宣称生产已生效。

## 最终固化与回执

- 已审源码提交：0a92fff22983df5aad931ca48a9b8573dda0e66c。
- 完整 R9 通过后核对提交 diff SHA256 仍为 ae5b285c114362227ffe1a3b826fc0df180dedbce23e50f75ec815d0de7980a7；未将未审修改夹入源码提交。
- 第二次 full R9 原始日志 SHA256：10f2c9e253132aebc1c73a6d3686272e084e28e6b077e3afb7a2d7455f38a01a。
- 第二次测试生成相同18份tracked reports，保存其diff SHA256 174668cb09aef85315f6015779744885f0790588ef7e43e46abcd50ce5d51dea 后按相同精确白名单恢复。
- 独立 full 原始回执：docs/governance/receipts/RECEIPT-20261015-rule28-obligation-independent-code-review.md。
- 独立 narrow 原始回执：docs/governance/receipts/RECEIPT-20261015-rule28-obligation-independent-code-review-narrow.md。
- 本结果报告与两份审查回执以独立文档提交保存；未将文档提交冒充已经完成独立源码审查。
- 本轮仅代码与维护契约固化，不是生产部署；规则实际执行效果、通用强制准入以及所有入口覆盖未在本轮验收。

审查原始返回（含原 Markdown 行尾两个空格）逐字保留于 docs/governance/receipts/RECEIPT-20261015-rule28-obligation-independent-code-review-raw.json，并记录各 raw_sha256。对应 .md 展示副本仅去除行尾空白以满足 diff-check，不改变裁决或正文。
