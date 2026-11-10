---
title: 技能清单全量重建会顺带批准未授权漂移 → 需按对象局部重建（--only）
scenario: 只需重新审批某一个技能（或少数几个），但清单里还有其他人未处理的漂移条目；或需要判断「某个技能到底是不是漂移」。
root_cause: 审批入口只提供全量重建，没有「按对象授权」的粒度；而基线的语义恰恰是逐对象背书，全量重写等于批量伪造批准。
solution: 用局部重建（--only，按 frontmatter name），未点名条目沿用原基线并在输出里显式列为「未获批的漂移」；目标不存在则整批不写。
evidence: "commit 81e59a5f8；scripts/approve_skills.py::_rebuild_only；tests/test_skills_integrity.py 新增 4 例（only_scopes_rebaseline_to_named_skill / only_unknown_skill_fails_without_writing / only_without_manifest_fails / only_matches_frontmatter_name_not_dir_name）；实跑输出: 本版仅重建 merge-review-gate，未批准列表 = article-review-gate、code-review-gate"
tags: [skills, manifest, 审批粒度, fail-closed]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-10T09:03:01.610713+08:00"
updated_at: "2026-11-10T09:03:01.610713+08:00"
---

现象: 技能完整性清单（skills/.manifest.json）落后于磁盘时，`scripts/approve_skills.py` 只能全量重建——它会按磁盘现状重写**所有**条目的 tree_sha256。于是「只授权批准 A」实际等于「顺带把 B、C 的漂移一起洗白」，而审批痕迹（approved_by/approved_at）看起来完全合法。

实证（2026-11-10）: 用户只授权重新审批 merge-review-gate，但当时的漂移面是 3 条：merge-review-gate + article-review-gate + code-review-gate（后者两条是他人遗留、未获本轮授权）。若跑全量重建，这 3 条会同时变成 ok，且扫描器不再报 modified——证据被抹掉，事后无法区分「谁批的」。

修复: 给入口加 `--only <name> ...`（按 SKILL.md **frontmatter name** 匹配，不是目录名）：
- 读当前清单 current，只把点名条目替换成新算出的条目，其余沿用 current 的 tree_sha256；
- 写盘后仍以磁盘现状重算一遍，把「未点名但已漂移」的条目**列出来**并给出可粘贴的下一句命令；
- 目标未知 / 无既有清单 → 退出 1 且不写入（fail-closed，不留半套基线）。

验证: 两组技能都改字节后跑 `--only target`：target→ok，bystander 仍 modified 且被打印；`--only ghost` 退出 1 且清单未变；无清单时 `--only` 退出 1；目录名 ≠ frontmatter name 时按目录名点不到、按 name 能点到（实例: skills/gzh-design-skill 的 name 是 gzh-design，所以按目录名判断漂移是错的）。

边界: 匹配口径是清单键（frontmatter name）。判断漂移必须用 loader 的 scan（按 name 查 manifest），不能用「目录存在性」自己造一套——否则会把改名目录误报成 unlisted。