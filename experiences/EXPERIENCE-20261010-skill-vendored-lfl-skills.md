---
title: 外部 skill/知识包 vendored 引入 LFL skills/ 的完整流程与坑
scenario: 把外部 GitHub 上的 skill/知识包引入本仓库 skills/ 并在运行时激活（vendored 吸收），以及后续任何人重复做同类事（引入外部代码/文档资产入库）时。
root_cause: ""
solution: 七步流水线：clone→裁剪拷贝→frontmatter/说明适配→扫描器预清扫→逐 skill 真实实测→分主题提交→publish+restart 激活。
evidence: "commit cb826ad8（7 skill 入库+适配）、395bd96a（遗留文档同步）；加载器复扫 31 skills 全标准解析；agent_search 真实检索 2 篇带 DOI；check_bibtex --self-test 全 PASS + 离线 PASS + 在线 429 正确报错；run_preflight 迷你档案端到端 2 ERROR+4 WARN 全命中；scan_anonymization/section_budget 实测通过；git 扫描拦截记录（SKILL.md:417、classifier_subagent_prompt.md:12、output_files.md:10）；service publish 首次因 dirty tree 被拒后补提交解除。"
tags: [skill-引入, vendored, git-安全扫描, python-环境, service-control, 验证纪律]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-10T08:18:01.411730+08:00"
updated_at: "2026-10-10T08:18:01.411730+08:00"
---

**流程（已在本任务全程实测）**：① 源 vetting 后 git clone --depth 1 到 /tmp（GitHub API 会 403，raw/clone 是可靠通道）；② 只拷需要的子集（SKILL.md+references+scripts+必要 assets+LICENSE/NOTICE，跳过 docs/webapp/tests），记录源 commit hash 写入 metadata.vendored-from；③ frontmatter 适配：description 中文化+触发词，删 allowed-tools，保留 license/metadata；正文顶部加「LFL 本地化说明」blockquote（裁剪范围/依赖事实/实测结果/上游文档缺口），只写已验证事实；④ **提交前必做**：grep -rlE '/Users/[A-Za-z0-9_]+/' skills/ 清扫上游文档示例中的本地绝对路径（git 安全扫描硬门），find skills -name __pycache__ -exec rm -rf（测试运行的产物）；⑤ 每个装进来的 skill 至少一次真实功能实测（不止 --help），上游引用但不附带的资产（如 preflight 的 venue 档案 schema.yml）要在说明里如实标注并给出可用的替代（从消费端代码 grep 字段构造）。**环境事实**：execute_command 不同 shell 的 python3 解析不一致（有 venv 上下文 vs homebrew python），pip 装包后务必用 `repo/.venv/bin/python3` 显式跑；PYTHONPATH 方式运行 skill scripts 时不要在 repo 根 cwd（会被 repo 自己的 scripts/ 遮蔽——这正是 paper-search-pro 纪律 A 的实证）。**外部事实**：Semantic Scholar 匿名请求本机易持续 429，脚本正确退避+报错；规模化用 S2_API_KEY。**服务激活**：publish 要求 tracked 工作区干净（遗留改动需先处理，程序不代 stash）；restart 参数名是 target 不是 restart_target；web/all 重启两阶段等待 requester 会话退出，受理≠完成，终态用 action_id 查 status。