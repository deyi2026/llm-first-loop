---
title: 权限 pattern 的「条目非空」不等于「可命中」：deny 裸目录名是静默 fail-open
scenario: "写域 scope 用 glob 匹配相对路径。`deny [\"src\"]` 解析成功、无告警，但 `_pattern_regex(\"src\")` 锚定为精确匹配，只命中 rel 恰为 `src` 的路径；而判定输入永远是文件相对路径（`src/x/y.py`），永不相等。实测 `scope_allows` 对 `src/llm_loop/core/sandbox.py` 返回 `(True, \"\")`：声明禁止目录，实际一个字节都没禁。原校验只查「归一后非空」（空排除集全量放行陷阱），未查「该条目能否命中任何真实写目标」。"
root_cause: ""
solution: "解析层对 deny 条目补目录语义：非 `/**` 结尾者存储为 `p + \"/**\"`。关键性质：`X/**` 的命中集 = `{X} ∪ {X 下任意层}`，且本身命中 `X`，所以对文件目标与原条目命中集相同（`deny [\"a.txt\"]` 仍排除 `a.txt`），对目录目标从「只排除目录自身」收紧为「排除整棵子树」；方向恒为收紧，allow 模式不经过该分支。不选「拒绝声明」：字符串无法区分文件/目录，会误伤精确文件条目。验证：修前 `(True,\"\")` → 修后 `(False,\"denied_by_deny_list\")`；9 个相关测试文件 679 passed / 2 skipped，新增 9 例含 allow 零回归；Pyright 0 errors。回执展示扩展后形态（`src/**`）即实际生效排除集，属诚实展示。"
evidence: "tests/test_write_scope_contract.py::test_deny_bare_directory_name_excludes_whole_subtree（src/./src/src/ /src 四形态）、test_deny_exact_file_entry_semantics_unchanged、test_deny_glob_pattern_expansion_idempotent、test_deny_mid_path_directory_name_excludes_subtree、test_allow_mode_unaffected_by_deny_expansion；9 文件 pytest 679 passed / 2 skipped；pyright 0 errors"
tags: [write_scope, fail-open, glob, 权限判定, deny, D1]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T15:33:03.358325+08:00"
updated_at: "2026-10-31T15:33:03.358325+08:00"
supersedes: [EXPERIENCE-20261031-write-scope-deny-模式下用裸目录名声明排除集是静默-fail-open-allow]
---

适用边界：任何「pattern → 判定集合」的权限系统（allow/deny 列表、gitignore 式排除、ACL glob）。

通用判据（可复用检查）：
1. 对每个 pattern 问「它能命中哪些真实输入」，而不是「它是否非空/格式合法」。
2. 若判定输入域与 pattern 的匹配域不同构（例：输入永远是文件路径，pattern 可能指向目录），则存在永不命中的条目。
3. deny 侧的永不命中 = 静默 fail-open，必须修；allow 侧的永不命中 = fail-closed，只是无效声明。

识别方法：不看解析器是否报错，直接构造一个应被拒的真实目标跑 `scope_allows`，看返回是否 True。本次即由此发现。

反例/易错点：
- 不要用「含不含扩展名/点号」猜文件还是目录。
- 不要改为「裸名在 deny 模式匹配一切」（反直觉，会让 `deny ["*"]` 语义漂移）。
- 不要只在判定函数里加前缀逻辑而不同步 `parse` 的存储形态——多个消费点会漂移；单一真值在解析层。
- `**` 自身不要扩展成 `**/**`（可匹配空 rel，形态退化）。