---
title: wheel 安装布局下 rules_version 恒为空：随包清单缺 ai_rules.lite.md 且两个读取点解析根不一致
scenario: 宿主用 wheel 安装 LFL（scripts/install_linux.sh：uv pip install wheel 到 releases/LFL-<ver>/venv）后，architecture_status 的 rules_version 恒为空、且工作区里找不到 docs/ai_rules.md，导致 AI 侧误判「规则真值源不可核验」。源码检出布局（如 .releases/<sha>/src）不复现。
root_cause: "随包清单（setup.py DOCS）只含 docs/ai_rules.md，不含版本信号文件 docs/ai_rules.lite.md；且两个 _rules_version() 读取点各自按模块位置推根（status.py 用 parents[3]、causality.py 用 llm_loop.__file__ 的 parents[2]），在 wheel 布局下都指向 site-packages/pythonX.Y，不含 docs/。规则索引（search.py）用的是 bundle_root() or parents[3]，能命中 _bundled/docs/ai_rules.md，所以「规则正文可读、版本信号为空」并存。"
solution: "三处对齐：1) setup.py 的 DOCS 增补 \"ai_rules.lite.md\"，使随包清单含版本信号文件；2) src/llm_loop/runtime/installation.py 新增 rules_doc_candidates()/rules_version()，候选根顺序=bundle_root()→源码检出仓库根→sys.prefix→site-packages；3) introspection/status.py 与 runtime/causality.py 的 _rules_version() 改为委托同一 helper（与 introspection/search.py 的 rule_root=bundle_root() or parents[3] 同源）。MANIFEST.in 同步 include docs/ai_rules.lite.md。"
evidence: "在隔离候选树（git archive HEAD + 补丁）上构建 wheel 并安装到干净 venv 做 A/B 实测（env -u PYTHONPATH，避免宿主 PYTHONPATH 污染）：before（现状 0.6.37 wheel）bundle_root=site-packages/llm_loop/_bundled；_bundled/docs/ai_rules.md exists=True；_bundled/docs/ai_rules.lite.md exists=False；status._rules_version()=''；causality._rules_version()=''。after（打补丁后 wheel）ai_rules.lite.md exists=True；status._rules_version()='20'；causality._rules_version()='20'。同时 RuleIndex(bundle_root()/'docs'/'ai_rules.md').search('RULE-AI-24',3) 在 before wheel 上即返回完整规则卡（含 synopsis），证明规则正文在 wheel 布局本就可达。源码布局下 27 个聚焦单测全通过（test_rules_version_resolution.py 新增 4 例）。"
tags: [packaging, wheel, rules_version, install-layout, linux, bundle_root]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T20:41:53.960163+08:00"
updated_at: "2026-10-28T20:41:53.960163+08:00"
---