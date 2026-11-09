# 审查与交付回执（正式落点）

本目录是 RULE-AI-28 各审查闸与交付证据回执的**正式落点**，自 2026-11-10 起生效。
命名 `YYYYMMDD-<issue>-<gate>[-narrow].json`；字段结构以对应闸的规则与 skill 为准。

## 为什么换到这里

旧落点 `docs/promotion/receipts/` 位于 `.git/info/exclude` 的 `docs/promotion/` 整目录规则之下：
回执写盘成功，但普通 `git add` / `git add .` **静默收不进**，只有 `git add -f <精确路径>`
才进历史；漏加不报错，回执只存在于本机。把落点移到未被忽略的目录后，「入库」成为
默认行为，而不是每次都需要记住的例外。

## 旧目录（历史归档）

`docs/promotion/receipts/` 自 2026-11-10 起**只读、不再新增**。已入库回执与历史文档中
对旧路径的引用保持原样（历史事实不改写，也不影响其可追溯性）。新回执一律写本目录。

## 机械保障（两条，缺一不可）

1. **目录不能被重新遮住**：`tests/unit/test_receipts_dir_versioned.py` 断言本目录与
   README 存在，且 `git check-ignore --no-index` 对本目录无命中。未来任何 ignore 规则
   把这里重新纳入忽略，测试直接变红。
2. **漏入库不能静默**：`.githooks/pre-push` 在推送时判定——存在未跟踪的
   `docs/receipts/*.json`，或本次推送新增/修改的回执仍含未回填占位字段，即拒推
   （fail-closed）。修复命令随拒绝信息直接打印。

## 边界

- 只放回执与证据，不放正文文稿。
- `docs/governance/receipts/` 是另一套（治理/合并回执），其既有闸不变。
- 回执一旦入库即为交付证据，不随后续改动重写；修订以新增回执表达。
