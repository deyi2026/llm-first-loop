# 2026-10-31 工作区回填补丁（桌面-浏览器线）

> ⚠️ **本目录下同名 `.patch`（sha256 `cd356e2a…`，15:06 生成）已作废**，与 canonical 版修改同一 hunk、互相冲突。请只用下面「canonical 补丁」一节指向的文件。
>
> | | 路径 | sha256 | 状态 |
> |---|---|---|---|
> | ✅ canonical | `<MIRROR>/data/deliverables/20261031/20261031-ws-backfill-desktop-browser-line.patch` | `35908353…` | **用这个** |
> | ❌ 作废 | `<MIRROR>/docs/design/20261031-ws-backfill-desktop-browser-line.patch` | `cd356e2a…` | 冲突，勿用 |

## canonical 补丁（唯一有效）

```bash
cp /Users/<user>/Project/llm-first-loop-mirror/data/deliverables/20261031/20261031-ws-backfill-desktop-browser-line.patch \
   /Users/<user>/lfl-workspace/docs/design/
cd /Users/<user>/lfl-workspace
git apply --check docs/design/20261031-ws-backfill-desktop-browser-line.patch   # 预演
git apply docs/design/20261031-ws-backfill-desktop-browser-line.patch
```

规模：**2 files / +189 −9**（设计书 843 → 916 行；交接书 220 → 327 行）。

**已验证**：在**仓库外**临时目录用工作区当前内容做过 `git apply --check` + `git apply` **真实应用**（非只读预演），结果为设计书 843→916 行、交接书 220→327 行，且新章节 `§11.8 续接会话收口` / `M4 投递通道首轮探针` 全部命中。

> 校验陷阱：在**仓库子目录**里跑 `git apply` 会**静默忽略** cwd 之外的路径并返回成功——看起来「应用成功」，文件其实没变。校验必须在仓库外做，或应用后**逐条 grep 核对新章节存在性**。

## 以下为旧版（15:06 补丁）说明，仅作背景

本会话完成了 **TASK-010 部署后 live 复验**（两条验收项均 PASS），但**写不进目标仓库**：

- `LFL_WORKSPACE_ROOT=/Users/<user>/Project/llm-first-loop-mirror/.releases/b008c9fae…`（本仓）；
- `<WS>=/Users/<user>/lfl-workspace` **不可写**——`edit_file` 快照报 `WorkspaceScopeMismatch`，shell 写探针返回 `Operation not permitted`（`sandbox-exec` 只放行工作区与缓存目录）。

因此「回填设计书 §11.8 + 更新交接书 §3/§4」改以**可 apply 的补丁**交付，落在本仓（当前唯一可写且可呈现的根）。设计书正本只存在于 `<WS>/docs/design/`，本仓 `docs/design/` 下**没有**该文件——本仓那份 `20261027-desktop-gui-and-browser-tooling-design.md` 不存在，所以回填只能在 `<WS>` 侧落地。

## 怎么用

```bash
cd /Users/<user>/lfl-workspace
git apply --check docs/design/20261031-ws-backfill-desktop-browser-line.patch   # 先验
git apply docs/design/20261031-ws-backfill-desktop-browser-line.patch
```

补丁已用 `git apply --check` 在该仓库根**预演通过**（只读校验，尚未写入）。改动规模：2 files / +102 −5，只动两份 Markdown，不碰代码。

## 补丁改了什么

**设计书** `20261027-desktop-gui-and-browser-tooling-design.md`（843 → 901 行）

1. 新增 **§11.8**：10-28～10-31 补丁回填（四笔提交与本文件记账关系）、§11.7 P2 建议与实际实现的四处差异、live 复验表（三项 PASS）、上限真值源与两层拒绝点、**五条未验证边界**。
2. §5.6 加「**2026-10-31 口径更新**」注：逐条更正那张 10-28 `dfb627bee` 快照（M3 已交付；`desktop_operate` 仍未实现；「L1 AX 不可读」只在 Chrome 成立；`type` 上限不在 schema 声明）。
3. 附录 B.1 / B.2 补证据索引（live 回执 ref + 源码锚点）。

**交接书** `20261031-handoff-desktop-browser-line.md`（220 → 259 行）

4. §2.1 补**提交日期订正**（四笔里只有 `4d7dc24ef` 出自 10-30）。
5. §3 表头更新 + 活跃写者注补 15:00 复核（mtime 仍是 14:38 / 14:16）。
6. §4 表 TASK-010 → `✓ done`；新增 **§4.1**（复验记录 + 三条订正 + 写侧边界）、**§4.2**（本补丁的用法）。
7. §8 陷阱 1/2 订正；末行状态更新为「已被续接会话核验并更新，但**未归档**——TASK-007/008 仍未收口」。

## 事实依据（A 级 live 回执）

| 事实 | ref |
|---|---|
| 部署快照（wecom gen 349 / `b008c9fae` / `matches_desired_generation=true` / barrier 空） | `evidence://v1/80c7f26ddcf0647975e860f94bc29183e6b22e46f070e96b7a7726aa8d960e61` |
| 仓快照（四笔 `merge-base --is-ancestor` 逐个为真；HEAD = 部署 + 1 提交；工作树脏） | `evidence://v1/819129e32855e1d5abdc7fd9082d551a70ef3cb03d0f9e2430f3f68ca017b167` |
| `desktop_perceive snapshot` → `binding=title_relaxed` / `degraded=["ax_title_relaxed"]` / 33 节点（活动监视器 window_id 89051） | `evidence://v1/05646b901e0a0c4bf9d88a2e46f5b4d248ec3a2787d7a392a9a7d652ee392f2f` |
| 桌面窗口清单（CG 标题「活动监视器」） | `evidence://v1/2be3d43aaf8836b69a537787fcffcb25f73b852aa5b24900dcd76dfd18b1ff18` |
| 桌面能力自检（`ax_trusted=false` 假阴性、截屏授权 true） | `evidence://v1/14bfe99bef9e6b90b484f8d257bbd4e28085c81ddc85d43a037458d5e51b5985` |
| `desktop_perceive snapshot` → `binding=title_exact` / `degraded=[]`（微信，标题一致对照组，13 节点） | `evidence://v1/3d7c5c698adae083b42eab45d3c2279d2381009111a4d625a39ce84ef35758e3` |
| 被拒后目标 textarea 仍为空（无 `value_text`） | `evidence://v1/12989a59855d369df7fbb3d3cbf41c83facc1b08e04bd3e3485c2a44c4e4e43a` |
| `type` 送 2222 字符 → `contract rejected; reason=type_text_too_long` | 会话内**失败回执**（失败回执未落 `evidence://` 持久引用） |
| 上限常量与两层拒绝点 | `evidence://v1/232fac4bd3195ce5601d733a3a570877bfb59fc2e416bf87ebf3a9a603336262`、`evidence://v1/a3e3203c7ca1edd4ef2c74372a5c3bf60a276aaa57d2db58a6b3f4922a426383`、`evidence://v1/d4fdf89b406da1364499371f0dd84616ce22e127d6393c2ee7d42f74af2abe12` |
| 四笔提交的日期与 diffstat | `evidence://v1/1493c5c2e57e7e833962fc533ffe7b76d9f145e68f1e1ecaed5d13fc77e87bb2` |
| `4d7dc24ef` / `55aff5b73` 实现细节 | `evidence://v1/aab737df5b8474fc775d95593c1006eb96c9be706f2695cd9c819634e0ecc455`、`evidence://v1/b119dcbe3aacc1753ce3b9acce9d6d6efa247119470ae532993fd70a370625a2` |

## 仍未验证的边界（别当已验）

1. `type` 的 **`=2000` 接受侧**未做 live 测试（只实测 2222 被拒）——要证明边界精确等于 2000，需向本地页面「视频描述」输入框真实写入 2000 字符，本轮为避免污染发布表单而未做。阈值以源码常量 `_TYPE_MAX_TEXT_LENGTH = 2000`（`browser/action.py:60`）为准。
2. **M4 / `desktop_operate` 仍未授权、未开工**：真实 AXPress、键入投递无 A 级证据。
3. **Chrome 网页层 AX 未变**（`-25211`）；本轮 PASS 只覆盖非 Chromium app。
4. 降级绑定在**多命中**时的歧义拒绝行为未重测（只验了单命中）；标题一致的对照组已验（微信 → `title_exact`、`degraded=[]`）。
5. `ax_trusted=false` 是原始 trust 位（已知假阴性），能力判据一律用探针。

## 使用时的禁令

- **不要把这两个文件 commit 进本仓**：本仓另一条 write-scope 线正在改 `write_scope.py` / `sandbox.py`（15:00 复核时 mtime 14:38 / 14:16），本补丁是给 `<WS>` 会话 apply 的，不是本仓产物。两个文件保持 untracked。
- **M4 仍未授权**（交接书 §1.2 / §5 红线）：本补丁不含任何桌面动作代码。
