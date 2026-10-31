# 技能完整性门禁口径（EVO-20261031-6b21e0f4）

> 本文件是 `skills/.manifest.json` 与 `LFL_SKILLS_REQUIRE_MANIFEST` 的**口径定义**。
> 口径由 2026-10-31 人工授权确定；实现见 `src/llm_loop/skills/loader.py`
> （清单 v2）与 `src/llm_loop/introspection/tools_skill_files.py`（门禁放行）。

## 1. 清单是什么

`skills/.manifest.json` 是**完整性基线（integrity baseline）**，记录每个技能的
**整个目录树**的 sha256（外加逐文件摘要）。

它证明的是：**磁盘上的技能与登记时一致**。

它**不**证明：内容被谁逐字读过、行为是否被人工认可。把两者混为一谈，
清单就成了伪造的审批痕迹——因此本口径把"完整性"和"质量审批"分成两件事，
清单只承担前者。

## 2. 为什么覆盖整棵目录树

只哈希 `SKILL.md` 的门禁是装饰性的：`SKILL.md` 只是指向 `scripts/`、`data/`、
`sections/` 的索引，**执行输入是那些文件**。

实测（本仓，2026-10-31）：`skills/ui-ux-pro-max` = 49 文件 / 3,330,378B，
其中三个是 823,933B / 747,241B / 433,127B，而 `SKILL.md` 只是其中之一。

v1 口径下「改了脚本、没改 `SKILL.md`」的变更会**完全隐身**。v2 改为目录树摘要，
并保留逐文件摘要，使拒绝理由能指名**改了哪个文件**。

## 3. 纳入范围

- **覆盖**：`skills/` 下每个含 `SKILL.md` 的一级子目录（当前 39 个）。
- **不覆盖**：标准包技能（`pkg/name` 形态）。它们由 catalog 的安装/版本机制
  保证完整性，不受本门禁约束。这是**已知边界**，不要误以为门禁是全覆盖。

## 4. 信任分层

清单条目记录来源：

| 字段 | 含义 |
|---|---|
| `source` | `local`（本仓自研）/ `vendored`（第三方 vendored） |
| `upstream` | vendored 技能的上游坐标 `repo@commit`（取自 frontmatter `metadata.vendored-from`） |
| `approved_at` / `approved_by` | 本版基线的生成时刻与批准者标识 |

门禁对两类一视同仁（都必须 `integrity=ok`）。但 vendored 技能的**内容授权依据**
是 `NOTICE.md` 记录的上游 commit 与许可，不是"人逐字读过 3.3MB"。

## 5. 门禁语义

开关：`LFL_SKILLS_REQUIRE_MANIFEST=1`（本机 `.env` 已开启；模板 `.env.example`
默认注释，注释中写明如何开启）。

开启后，**只放行 `integrity=ok`** 的技能。四态：

| 状态 | 含义 | 门禁下 |
|---|---|---|
| `ok` | 已登记且目录树摘要一致 | 放行 |
| `modified` | 已登记但内容变了 | 拒绝 |
| `unlisted` | 有清单但该技能未登记（含登记条目缺 `tree_sha256`） | 拒绝 |
| `unmanaged` | 无可用清单（缺文件/损坏/版本不符） | 拒绝 |

缺清单时**全部技能都会被拒**（fail-closed）。这是有意的：没有基线就没有
"一致"可言。

## 6. 谁批准 / 怎么改

- 基线生成入口：`python scripts/approve_skills.py [skills_dir] [--approved-by <标识>]`。
- `--approved-by` 默认 `baseline`，语义是"由脚本按磁盘现状生成，**不代表内容
  已被人工逐字审阅**"。人工复核后应写入具体标识。
- **AI 代跑允许，但不得冒充人工审阅**：不得把机器生成的基线记成人工签字。
- 改了技能之后必须重跑该脚本，否则该技能在门禁下不可加载（这是设计意图，
  不是故障）。

## 7. 诚实边界（不可省略）

1. **清单与技能同在 AI 可写的工作区内。** AI 可以同时改两者。本机制是
   **篡改可检测 + 加载需过基线**，**不是**防篡改强隔离。要做到强隔离，需把
   清单移出工作区或只读挂载——本轮未做，属于未覆盖项。
2. **真正的分界在推送环节**：`skills/` 的任何改动都会进入 git diff，必须通过
   `review_admission` 的独立审查才能推上远程。本地写盘层的"自批"是已知边界。
3. **vendored 大资产的审查是结构性的**：单文件超限时按 head/tail 投影送审
   （见 `review_host_admission.py` 的 `_VENDORED_ASSET_PREFIXES`），审查者看到
   路径、字节数、边缘内容与显式省略标记，**看不到完整全文**。这是容量与门禁
   强度之间的显式取舍，不是"已完整审查"。

## 8. 相关文档

- `scripts/approve_skills.py`（入口与诚实边界说明）
- `src/llm_loop/skills/loader.py`（清单 v2 结构与四态判定）
- `tests/test_skills_integrity.py`（口径的回归测试）
