# LFL 本地模型重复/漂移 v0.5：独立设计审查 PASS

- 日期：2026-11-14
- 冻结设计：`docs/ANALYSIS-20261114-local-model-repetition-root-cause.md`
- 设计 Git commit：`d4735b91a937fc09d5c44bd8ecb5d2720f8ab9d2`
- 设计 SHA256：`96220978276263e6511bdc1e4ea0d00278f0398f7554d0ee3e955dd02c88dab1`
- 外部证据 SHA256：`3d804fcbba0b5945c535ee16154ddd88060cfc5a7fcd94fe630d49b054fb749f`
- 独立 Reviewer：`glm/glm-5.3`，真实单次调用，零工具，`finish_reason=stop`，`truncated=false`，结构/身份校验无错误
- **正式裁决：PASS，P0=0/P1=0/P2=1；12/12 对抗性设计验收 PASS**

## 事实与审查范围

1. 事故请求声明 Ornith-MLX，但 Provider 文件 SHA 与日志一致、端点 8901 当前为 2026-10-22 启动的 Qwen3.8 GGUF llama-server；**历史实际权重/线包仍 UNKNOWN**。禁止迁移 MLX 资格或直接改生产配置。
2. 首 Run 8 轮的模型结构指纹、2 条消息、101 工具一致；7 次完整工具交换被归档后仍恢复同一结构投影。Evidence 原始 blob、owner 权限、归档恢复均通过，**但模型实际收到恢复引用仍未证明**。
3. 事故源码五个关键文件 Git blob OID 与本地 main 一致；84 条压缩预算统计绑定冻结 EventLog SHA。仅支持历史事件级 RED，不冒充代码级或 HTTP 字节级证明。

## P2 与测试证据

Reviewer 唯一 P2：105 项连续性测试和 72 项 Evidence 测试原先缺独立 SHA 绑定。
已在同一未改动源码/测试 Git tree 下重新运行两组，`105 passed`、`72 passed`，两组 `exit 0`，命令、Git tree OID 与日志 SHA 记录于
`docs/governance/receipts/RECEIPT-20261114-local-model-repetition-v05-tests.json`。
**这是审后证据补齐，不将 Reviewer 原始 P2=1 改写为 P2=0。**

正式 Reviewer 回执：
`docs/governance/receipts/RECEIPT-20261114-local-model-repetition-v05-glm53-review.json`。
P0-A 证据绑定：
`docs/governance/receipts/RECEIPT-20261114-local-model-repetition-v05-P0A.json`。

## 下一阶段门禁

**设计 PASS 只允许进入新的隔离实施阶段，不能直接上线。**
先完成事故预算 3698 字符/101 工具/`max_tokens=32768` 的**代码级离线 RED**，在最终 pre-send 视图核验 `raw exchange` 或可授权分页的 `exact-ref`、tool-call pairing、current human ingress、实际 backend/model identity；未满足则拒绝外发、标记 `run_incomplete`，绝不自动重发工具或因相似调用自动停止合法探索。

RED 后由单一 GLM-5.3 开发代理实施最小接线补修；冻结代码候选后交独立 Reviewer（PASS、P0/P1=0），再跑原版完整 R9 exit 0、远端 CI，最后经明确发布授权完成 main/push/受管发布。

**本轮未修改业务代码、模型配置或 M5 Goal，未执行 R9、main 合并、push、生产发布、服务重启。**
