---
title: SWE-bench Django 全量做题经验（9 批 130 实例：标准流程+修复模式库+环境教训+纪律）
scenario: 继续 SWE-bench django 全量（剩余 101，batch10-20）；或任何 SWE-bench 评测任务（取实例→修复→验证→导出）
root_cause: SWE-bench 做题是高频长流程（每实例修复+本地验证+官方终验），环境兼容与纪律边界是最大时间成本；不做系统性沉淀会导致每批重复踩坑（镜像平台/限流/容器冲突/环境差异）
solution: 标准流程 5 步：① 只看 problem_statement+test_patch（杜绝 gold patch）；② py3.11 venv + pip install -e .（老 Django 必须 3.11）；③ tests/runtests.py 复现 F2P→改 django/ 源码→模块回归；④ git diff -- django/ 出 patch（不含 tests/）；⑤ 官方 harness docker 终验。模式库（命中即复用）：delete() 字段选择优化（11749/11087）、OuterRef in exclude 模型错用（11734）、fast-delete 合并回归（11885）、环境差异先 git stash 区分 base/修改。环境教训：arm64 主机 x86_64 镜像 404 需补拉、Docker Hub 429 需串行+间隔（manifest inspect 探测不耗配额）、容器冲突清理重跑。纪律：不看答案、网络测试容器无外网失败标注环境限制、批次拆解留痕 status.json。进度：每批 jsonl 落盘 + 批间新会话（100 万窗口）。详见 experiences/EXPERIENCE-20260820-swe-bench-django-full.md
evidence: batch1-9 官方 harness 报告 130 实例 resolved；完整文档 experiences/EXPERIENCE-20260820-swe-bench-django-full.md；批次计划 data/swe_results/django_remaining_plan.json
tags: [swebench, django, 评测流程, 修复模式, 环境教训]
source: {}
status: active
created_at: "2026-08-20T02:11:03.909178+08:00"
updated_at: "2026-08-20T02:11:03.909178+08:00"
---