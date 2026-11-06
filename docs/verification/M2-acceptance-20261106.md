# M2 批次验收记录（D-03 / B-01 / B-05）

日期：2026-11-06（Asia/Shanghai）
分支：`browser-m2-batch`（基线 b65f2f8f9 → 37c77f66b / 4c9116dda / 59bb82779 / b7b2d5a8e）
依据：`docs/promotion/LFL_Computer_Browser_Audit_Requirements_Design_2026-11-06.md` v1.1 §5.4/§5.5/§5.6/§6/§7

## 离线回归

| 面 | 命令口径 | 结果 |
|---|---|---|
| desktop 全部相关 | `pytest tests/unit -k "desktop or ax_ or paging or macos"` | **374 passed** |
| browser 全部相关 | `pytest tests/unit -k "browser"` | **851 passed** |
| 新增用例 | subtree_v03（5）/ budget_v03 / fill_pipeline_v03（8）/ scroll_scope_v03（3） | 全绿 |

T-06（页宽 1/200/500 覆盖一致、游标不指向必拒页）与 T-07（1500 边界外定向续读可达）由 budget_v03 / subtree_v03 / paging_v01 更新覆盖。

## 现场验收（真实 Chrome 156 + CDP file:// 受控页，2026-11-06 晚）

动作经 worktree 新实现 `CdpBrowserMutationActuator` 直驱；页面经 `http://127.0.0.1:9229/json/new` 打开，验收后已关闭并清理临时文件。

| 项 | 断言 | 实测 |
|---|---|---|
| T-08a 接受型受控组件 | `input_pipeline=insert_text`，readback 无 mismatch | ✅ |
| T-08b 回滚型受控组件 | 诚实报 `set_text_readback_mismatch`，actual 回滚值 | ✅ expected=SHOULD-FAIL / actual=FIXED |
| T-08c maxlength=5 | 截断事实进 readback | ✅ actual=01234 |
| T-08d append | 拼接语义 + DOM 复核 | ✅ hello-world |
| T-12 内层容器滚动 | scope=container、有位移、页面 scrollY 不变 | ✅ before=0→after=200，max=1820，页面 0/0 |
| T-16 开启方向 | 回执带管线标识 | ✅ input_pipeline=insert_text |

T-16 关闭方向（legacy_degraded 不可达验证）：离线已按 RULE-AI-35 实测（`test_t16_switch_off_routes_legacy_with_degraded_marker` + 参数化 on 变体），现场关状态不单独复测（env 由宿主管辖）。

## 与审计条目对照

- FR-03/D-03：累计 600 预算语义统一（total_cap+stop_reason+coverage），不发必拒游标；subtree 定向续读全局 ref 编码。
- FR-04/B-01：replace=focus+全选+insertText；append=focus+光标末+insertText；回读 RAF+宏任务等重渲染后再取值；mismatch 如实上报不假成功。
- FR-08/B-05：最近可滚祖先优先（overflow+溢出判定），页面仅回退；回执带 scope/before/after/max。
- NFR-03：schema 描述同步（fill 管线与开关、scroll 作用域）；legacy 通道回执显式 `legacy_degraded`。

## 未覆盖与边界

- contenteditable 与真实 React 站点未做现场样本（受控组件语义以原生模拟页等价覆盖 reconciliation 时序）；M3 集成验收补充。
- iframe 内容器滚动未单独现场验证（脚本按 DOM 树向上找祖先，同源 iframe 需 M3 复核）。

## 独立审查 P2 跟进（subagent_14cd2790e45a，P0=0/P1=0/P2=4）

1. scroll 移除旧 `scrollIntoView({block:'center'})`：审计 FR-08 语义优先（容器作用域），回执事实已缓解；依赖「滚动后目标可见」的下游流程若回退，M3 以 `scroll_into_view` 动词补显式入口。**跟进备注，本批不改。**
2. fill 在不支持选区的元素（contenteditable 等）上错误信息晦涩 → **已修**：选区建立失败时抛带指引的可行动消息（contenteditable 属 M3，legacy 开关路径明示）。
3. desktop subtree 释放语义仅有 fake 组合层验证，无真实 CF 子项现场 → 如实记为**验证缺口**：现场需新 runtime 部署 + TCC 授权进程，随 M3 集成验收补（与既有「现场回读」边界一致）。
4. `deepest_covered_ref` 派生自过滤后节点，尾随节点被 node_kinds 过滤时恢复提示可能指向偏宽父级 → 次要，**M3 跟进**（候选：分页时记录未过滤边界索引）。
