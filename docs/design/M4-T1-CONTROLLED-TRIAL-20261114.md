# M4 · T1 受控试用：Mac 隔离验收与正式入口决策（2026-11-14）

## 状态与权威边界

- **M4-A（本轮）**：隔离工作树、真实 loopback TCP/HTTP + Uvicorn + FastAPI 路由 + BackgroundRunner + LLMClient 合成 SSE + EventStore + TaskBudgetStore + FileService 的链路验收。**合成 Provider**，不消耗真实 GLM、不发布、不触碰生产用户文件。
- **M4-B（待 operator 另行确认）**：真实 GLM-5.3 的一个受控 Web Run。必须由 operator 明确确认 session、workspace、唯一目标、日期窗口、停止条件后再签发 0600 配置；不得用 M4-A PASS 冒充 M4-B PASS。
- 基线：GitHub `main` = `7f8c320d31fcd57874cebc99010ddb4a9df15f6a`，tree = `035f78d6721d10c78b94fb2941032369084e938a`，Mac 受管 generation 408，四服务 verify=ok，barriers=[]。**Web T1 operator config 默认未配置**（两种配置根路径只读核验）。
- 唯一写域：本隔离试验的 pytest `tmp_path` 下 `docs/target.md`；禁止编辑现有用户资料、dirty main、已发布 release 工作树、Deepin 或外部平台。

## 责任与范围

| 角色 | 本阶段职责 |
| --- | --- |
| Operator（用户） | M4-B 真实调用前批准具体单文件、session、试用窗口；保留撤销权 |
| LFLM2 执行代理 | 在独立工作树执行 M4-A；不得改变生产配置、重启或扩大授权 |
| ChatGPT 父侧验收 | 复核 HTTP 事实、实际文件字节、EventStore/预算账本、退出码与负向拒绝 |
| GLM-5.3 独立 Reviewer | 对冻结的新增测试与证据做只读审查；不代替 operator 授权 |

## 样本与验收矩阵

| 样本 | 动作与证据 | PASS |
| --- | --- | --- |
| A01 正向 | 真实 loopback HTTP POST → Uvicorn → FastAPI → Runner → LLMClient 合成 SSE → read snapshot → edit CAS；三笔 Provider、两笔 Tool 均 settled | 目标仅日期变更、EventStore opened/settled join 与账本一致，SSE run_started/tool_round/done 无 error |
| A02 撤销 | 真实 0600 operator 配置装配 `build_app`，放行首个请求；chmod 0644 后同一 app 再发请求 | 第二次拒绝，零新增 Runner 派发 |
| A03 入口隔离 | stream 放行、同步 route 拒绝 | sync 409 `budget_canary_requires_stream` |
| A04–A07 负向 | 未认证、错模型、未认领 queue_id、附件 | 400/403/409 拒绝；零 Runner 派发、零预算文件 |
| A08 预算/恢复回归 | 原版 M1/M2 96 项专项（含 CAS、撤销、并发单飞、UNKNOWN、usage 对账） | 全部通过，真实 exit 0 |

M4-A 不新增第二账本、不更改生产代码、无真实网络 Provider egress。单独的 loopback HTTP 测试放在 `tests/unit/test_m4_t1_loopback_smoke.py`，复用既有 M2 测试事实和 fixtures，仅将 in-process TestClient 替换为 127.0.0.1 TCP/Uvicorn；socket 按每个请求启动并关闭。

## 试用窗口、预算与停止

- M4-A 执行窗口：2026-11-14 11:10–11:15（UTC+08:00），限本地合成流。
- M4-B 尚**未安排窗口**。获批后使用一次性、最长 30 分钟的 operator 配置；一个 session、一个 Run、一个目标文件；只准 `read_file`、`edit_file`，不准子代理、外发、发布、系统命令或任意写域。
- 现行代码硬上限：4 次物理 Provider attempt、3 次 Tool、输入与输出各 400,000 tokens、目标文件不超过 2 MiB；本试用目标流程是 3 Provider + 2 Tool，**不得将目标值误报为已实现的更小硬上限**。
- 立即停止：operator 配置删除/变更/权限放松、身份不符、无权威 snapshot、CAS 冲突、usage 缺失或超预留、UNKNOWN 债务、跨 kind 并发超过 1、预算超限、意外文件变更、非预期网络外发、服务健康异常。
- 任一 stop 只能保留事实和拒绝进一步副作用；不得自动重试 UNKNOWN、放宽门禁或改写历史回执。

## 验收结论与下一门

M4-A 初测：既有 M1/M2 **96 passed**；新增真实 loopback HTTP **7 passed**；Ruff **PASS**；Pyright **0 errors**。见 `docs/receipts/M4-T1-LOOPBACK-20261114.json`。M4-A 证明 OS loopback HTTP 级链路与负向拒绝，不证明真实 GLM 运行、生产 Web 开关或真实对外发布。

**下一门**：冻结本候选 → 独立 GLM-5.3 审查 → 按代码变更门禁决定原版完整 R9 → GitHub CI/main；M4-B 在 operator 对真实单文件试用另行授权前维持 OFF。Mac 四服务不因 M4-A 重启。
