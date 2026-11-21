---
title: 跨稿派生脚本里新插入的断言必须放在被引用变量定义之后，否则首跑即 NameError
scenario: 把上一班的发布脚本跨稿派生（sed 替换期号 + 手工插入防漂移断言）时，新插入的断言放在了被引用变量的定义之前：断言用到 HTML 与 ADMIT 两个模块级路径常量，而它们在文件里定义在断言之后 → 脚本首跑就 NameError，发布链路在开页阶段就断（d100 实测）。同类风险：断言放在条件分支内却引用尚未解析的名字、放在 import 段但名字在后面才定义。
root_cause: ""
solution: 派生脚本里插入断言时，先确认被引用标识符已定义：把断言放在变量定义之后（或改用运行期再断言）。断言内容要同时钉住「源稿路径」与「派生产物路径」，避免只钉一半导致静默产出旧稿。
evidence: "docs/promotion/_d100_publish.py：派生插入的 assert 位于 HTML/ADMIT 定义之前，首跑抛 NameError: name 'HTML' is not defined；修正脚本 receipts/d100research/_patch_publish_d100.py 把断言移到定义之后，随后 open/state 两步均成功（编辑器 ready、标题框在、AI 声明标签在）。"
tags: [LFL推广, 派生脚本, 断言, 发布链路, d100]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-19T20:30:25.700211+08:00"
updated_at: "2026-11-19T20:30:25.700211+08:00"
---

1. 跨稿派生脚本（发布/构建/校验类）里加断言时，先确认被引用的变量已在文件里定义；断言放在变量定义之后，或改成运行时再断言。
2. 派生脚本的断言要同时覆盖「源文件」与「派生产物路径」（稿名、html、admission 回执、session 文件、图文件名）。
3. 派生后必须 grep 旧期号与旧稿名，确认没有残留引用（d100 沿用这条：派生脚本里无 d99/daily-99 残留）。
适用边界：sed/字符串替换式跨稿派生脚本。
反例：把 assert 插在被引用变量定义之前 → 脚本首跑 NameError，发布链路在开页阶段就断。
当前性验证：跑 `python3 -c "import ast,sys; ast.parse(open('docs/promotion/_d100_publish.py').read())"` 应无 SyntaxError；再 `grep -n "daily-99\|d99" docs/promotion/_d100_publish.py` 应无输出。