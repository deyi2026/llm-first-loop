# 唯一工作区变更协议（Workspace Change Protocol）

> 前身: 镜像工作区协议 MIRROR-workspace-protocol.md（2026-08-20 生效；2026-09-29 主区退役后更名改写）。

> 生效: 2026-08-20（用户批准）；2026-09-29 修订（用户指示：主区退役，本区即唯一区）| 状态: 强制 | 适用范围: **一切涉及 LFL 自身代码/文件的修改**
> 拓扑事实（2026-09-29 起）: 本工作区（原镜像 `*-mirror` 目录，web :8903）是**唯一生产区**——
> 原主区（同级 `llm-first-loop` 目录，:8902）已物理删除，不存在"审批后应用到主区"的跨区同步。
> 历史上的主区-镜像双区流程仅作背景保留在 Git 历史；本文件只描述唯一区变更门禁。

## 1. 为什么（背景）

- 2026-08-20 一天 6+ 次 prompt/.env 改动 → 每次全量缓存失效 + 运行态风险；
- 慎重原则：LFL 自身代码/文件（src/、docs/ai_rules.md、prompt.py、.env、scripts/、tests/、webui/）的任何修改，**先验证、经用户审批后才能生效并重启**。

## 2. 强制流程（LFL 自身代码/文件修改一律走此流程）

```
① 在本工作区修改（唯一区）
② 在本工作区验证
   - 单元测试全量通过
   - 行为验证（web :8903 chat 实测：回答质量 / 规则读取 / 无回归）
   - 涉及 prompt/.env 的：命中率观察（排除 web 探测窗口）
③ 产出 diff + 验证证据，提交用户审批（明确说明: 改了什么/验证了什么/影响面）
④ 用户批准后，在本工作区提交生效 + 重启（经 scripts/restart_mirror.sh，脚本名为历史遗留）
   - 提交前任一步失败 → 不提交不重启，工作区改动保留待修正
```

## 3. 操作速查（本区即唯一区）

```bash
# 测试（.venv 为本区独立目录，editable 安装指向本区 src——无 PYTHONPATH 顾虑，
# 该顾虑源于已退役的"共享 venv 指向主区"双区拓扑，2026-09-29 核实失效）
cd <本仓库根> && .venv/bin/python -m pytest tests/unit -q

# web / 飞书桥（web 端口 8903）——一律经 restart_mirror.sh（环境隔离/回执落盘/
# 预检门内置）；手写 nohup 启动已废止（2026-09-14 红线）
cd <本仓库根> && bash scripts/restart_mirror.sh web        # 亦可用 feishu / all / status

# 产出 diff（用于审批）
git diff
```

## 4. 边界与例外

- **必须走门禁**：src/、docs/ai_rules.md、prompt.py、.env（配置）、scripts/、tests/、webui/ 源码；
- **不走门禁（运行态）**：data/ 下的运行时状态（记忆写入/经验沉淀/事件日志/会话数据）——这是 LFL 正常运行的一部分，不是"修改"；
- **用户直接指令**：用户明确指示立即执行（如紧急修复）时，可豁免审批但须事后补验证说明。

## 5. 验证证据格式（审批时提交）

```
改了什么: <文件清单 + 核心 diff 摘要>
验证了什么: <测试结果 / 行为实测 / 命中率数据>
影响面: <涉及前缀? 涉及运行中会话? 回滚方案?>
```

## 6. 相关

- P2 规则文件解耦: docs/ARCHITECTURE-cache-stable-rules.md
- 本协议是 LFL 自身变更的强制门禁；P2 落地后规则将移入 lite 文件（届时本协议并入规则文件）。

## 7. 历史遗留与现状（2026-09-29 核查，取代原双区隔离表）

| 内容 | 现状 | 说明 |
|---|---|---|
| data/ | **本区即权威源** | 原约定"权威源=主区 data/"已随主区退役失效 |
| webui/dist | 本区独立副本 | rebuild 即生效，无需跨区重建 |
| .venv / webui/node_modules | 本区独立目录 | editable 安装已指向本区 src（实测 import 路径=mirror/src）；新增依赖仍须先审批 |
| experiences/ skills/ | 本区即权威源 | 原"经 promotion 带回主区"流程已失效 |
| .env | 本区生效值 | 配置变更仍走门禁（diff 列入审批） |
| 端口 | web :8903 | 原为避开主区 8902；主区退役后 8903 保留为既定端口 |
| Python 包解析 | 默认解析到本区 src | 无需 PYTHONPATH（历史双区风险已消除） |

**总则**：本工作区是唯一运行时权威（代码/数据/经验/配置生效值）；不再存在第二权威区或跨区 promotion。

## T0 工作树治理（2026-09-16）

- 代码根事实源链：现役服务以 `data/runtime/runtime_manifest.json` 的
  `workspace_root` + `data/restart-receipt.json` 为准，不以 mirror 主检出的分支/HEAD 推断。
- worktree registry：`data/audit/worktree_registry.json`（bootstrap 见
  `scripts/bootstrap_worktree_registry.py`）。默认全部标 legacy；protected 仅
  现役 code root 与显式回滚候选；retired 为人工标记；**永不自动删除**（A4 GC 9/19 再议）。
- 嵌套禁令：禁止在任何 linked worktree 内部再建 worktree（2026-09-16 事故：
  判基线 worktree 误建于现役 code root 内，弄脏 dual-root clean 校验）。创建前
  `bootstrap_worktree_registry.py --check-add <path>`；restart preflight 亦拒绝。
- 会话环境残留 `LFL_RESTART_CODE_ROOT` 是高危默认值：官方重启调用必须显式双根
  导出并按需 `LFL_RESTART_CODE_ROOT_CONFIRMED=1`（见 restart guide §12）。
