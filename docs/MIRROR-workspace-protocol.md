# 镜像工作区协议（Mirror Workspace Protocol）

> 生效: 2026-08-20（用户批准）| 状态: 强制 | 适用范围: **一切涉及 LFL 自身代码/文件的修改**
> 位置: 主区 /Users/yyj/Project/llm-first-loop · 镜像 /Users/yyj/Project/llm-first-loop-mirror

## 1. 为什么（背景）

- 2026-08-20 一天 6+ 次 prompt/.env 改动 → 每次全量缓存失效 + 运行态风险；
- 慎重原则：LFL 自身代码/文件（src/、docs/ai_rules.md、prompt.py、.env、scripts/、tests/、webui/）的任何修改，**先在隔离环境验证，无误后经用户审批才能更新到主区**。

## 2. 强制流程（LFL 自身代码/文件修改一律走此流程）

```
① 在镜像工作区修改（/Users/yyj/Project/llm-first-loop-mirror）
   - 环境与主区一致（.venv / node_modules / webui/dist 符号链接同源）
   - 镜像 web 端口 8903（主区 8902 不受影响），独立 data/（会话/记忆/日志隔离）
② 在镜像验证
   - 单元测试全量通过
   - 行为验证（镜像 8903 chat 实测：回答质量 / 规则读取 / 无回归）
   - 涉及 prompt/.env 的：命中率观察（排除 web 探测窗口）
③ 产出 diff + 验证证据，提交用户审批（明确说明: 改了什么/验证了什么/影响面）
④ 用户批准后，才应用到主区 + 重启
   - 任一步失败 → 主区零接触；镜像可弃可重建
```

## 3. 镜像操作速查

```bash
M=/Users/yyj/Project/llm-first-loop-mirror
# 同步镜像（拉取主区最新代码，排除运行时数据）
rsync -a --exclude='data' --exclude='.venv' --exclude='webui/node_modules' \
  --exclude='.DS_Store' --exclude='*.pyc' --exclude='__pycache__' \
  --exclude='.pytest_cache' --exclude='.ruff_cache' --exclude='.coverage' --exclude='logs' \
  /Users/yyj/Project/llm-first-loop/ $M/

# 镜像测试（在镜像目录，用主区同一解释器）
cd $M && .venv/bin/python -m pytest tests/ -q

# 镜像 web（端口 8903，独立数据）
cd $M && set -a && source .env && set +a && WEB_PORT=8903 nohup .venv/bin/python -m llm_loop.web > data/mirror-web.log 2>&1 &

# 产出 diff（镜像 vs 主区，用于审批）
diff -ru /Users/yyj/Project/llm-first-loop/src $M/src   # 按目录逐个
# 或 git（镜像含 .git 副本）: cd $M && git diff
```

## 4. 边界与例外

- **必须走镜像**：src/、docs/ai_rules.md、prompt.py、.env（配置）、scripts/、tests/、webui/ 源码；
- **不走镜像（运行态）**：data/ 下的运行时状态（记忆写入/经验沉淀/事件日志/会话数据）——这是 LFL 正常运行的一部分，不是"修改"；
- **用户直接指令**：用户明确指示立即在主区执行（如紧急修复）时，可豁免镜像但须事后补验证说明；
- **镜像自身不可修改主区文件**（隔离边界）。

## 5. 验证证据格式（审批时提交）

```
改了什么: <文件清单 + 核心 diff 摘要>
验证了什么: <测试结果 / 行为实测 / 命中率数据>
影响面: <涉及前缀? 涉及运行中会话? 回滚方案?>
```

## 6. 相关

- P2 规则文件解耦: docs/ARCHITECTURE-cache-stable-rules.md
- 本协议是 LFL 自身变更的强制门禁；P2 落地后规则将移入 lite 文件（届时本协议并入规则文件）。

## 7. 隔离边界与共享点（防混乱，2026-08-20 实测核查）

| 内容 | 状态 | 约定 |
|---|---|---|
| data/（会话/记忆/事件日志/审计） | **完全独立** | 镜像 data 只是工作副本，runtime 权威源 = 主区 data/ |
| webui/dist | **独立副本**（非符号链接） | 镜像 rebuild 不影响主区 UI；主区 UI 变更经审批后重建 |
| .venv / webui/node_modules | **符号链接共享** | **镜像侧不装新依赖**（P2 无新依赖）；确需安装先审批，统一装两边 |
| experiences/ skills/ | **独立副本（会漂移）** | 权威源 = 主区；镜像工作产出的经验/技能经 promotion 带回 |
| .env | **独立副本（会漂移）** | 配置变更在镜像改，审批时列 .env diff，promotion 一并应用 |
| 端口 | 8902 主区 / 8903 镜像 | 互不监听 |

**防混乱总则**：运行时权威（记忆/经验/会话/配置生效值）永远以主区为准；镜像只是"变更实验场"，其任何产出只有经审批 promotion 才进入权威源。
