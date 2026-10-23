# LFL 实时多模态 M0 本地语音栈能力档案（能力冻结）

> - 特性名：`realtime_multimodal`　阶段：**M0 / T-M0-2（能力与基线冻结）**　日期：2026-10-23
> - 权威依据：`docs/SPEC-20261023-realtime-multimodal-requirements-v1.md`（v1.2，163 条）、`docs/DESIGN-20261023-realtime-multimodal-architecture.md`（v1.3）、`docs/TASKS-20261023-realtime-multimodal-implementation.md`（v1.1）
> - 实测来源：`~/Project/research/docs/本地实时语音模型下载推荐-20261023.md`、`~/Project/research/voice-stack/`（仓库外，服务级验证）
> - 状态：**能力档案已按本地栈冻结**；**浏览器链路未接通**，相关条目为**部分解除**。**未写 PASS**。

---

## 1. LocalStackProfile（本地栈冻结，三态：官方 / 实测 / 未知）

| 能力项 | 值 | 官方 | 实测 | 未知 |
| --- | --- | --- | --- | --- |
| 统一运行时 | `mlx-audio`（MLX 原生，OpenAI 兼容 REST + WS） | ✔ | ✔ | |
| 主 ASR（增量流式） | `mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit`（0.72 GB） | — | ✔ | 许可=**未知** |
| 终稿 ASR（高精度校正） | `mlx-community/Qwen3-ASR-0.6B-8bit`（0.78 GB，apache-2.0） | ✔ | ✔ | |
| 流式 TTS | `mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit`（0.91 GB，apache-2.0，24 kHz，9 音色含 5 中文） | ✔ | ✔ | |
| VAD | `mlx-community/silero-vad`（<0.05 GB，server realtime 依赖） | — | ✔ | 许可=未知 |
| 本地主脑（文本） | Ollama `qwen3.5:35b-a3b-q4_K_M`（23 GB） | ✔ | ✔ | 许可待核实 |
| 传输（**唯一**） | 本地 `WS /v1/realtime`（**仅转写**）+ 本地 `HTTP /v1/audio/speech`（TTS 编排） | ✔ | ✔ | |
| 输入音频格式 | **16 kHz PCM 单声道**（`input_audio_buffer.append`） | ✔ | ✔ | |
| TTS 输出格式 | `response_format` wav/pcm/mp3；**整段返回，非分块流式** | ✔ | ✔ | |
| 最终转写事件 | `conversation.item.input_audio_transcription.delta` / `.completed` | ✔ | ✔ | |
| 轮次结束语义 | 客户端 `commit` → `.completed` | ✔ | ✔ | |
| 取消能力 | 本地链路可在客户端**立即停播**；**无服务端音频输出可取消**（WS 仅转写） | — | ✔ | 服务端取消语义=未知 |
| 播放截断能力 | 由**客户端** `PlaybackQueue` 承担（无 Provider 音频通道） | ✔ | ✔(服务级) | 浏览器侧未测 |
| 工具调用关联 | **无** Provider 工具回环（WS 无 `function_delta`）→ 桥接编排 | ✔ | ✔ | |
| 图像支持 | **无**（本地栈不含视觉） | — | ✔ | |
| 恢复方式 | **`local_rebuild_only`**（无远端恢复令牌） | ✔ | ✔ | |
| 连接限制 | 本机回环；单会话；WS 转写会话 | — | ✔ | 并发上限=未知 |
| 用量字段 | 本地栈无计费单位（自建；按耗时/字符登记） | — | ✔ | 结算口径=未知 |
| 地区/网络实测条件 | 全本地回环，无外网依赖 | ✔ | ✔ | |

> 撤销设计 v1.2 的“必须远端实时 Provider”默认假设（`RTM-CAP-11`）；**不写远端空适配器**（远端 D2 仅预留）。

---

## 2. RuntimeConstraint（运行时/环境约束，CAP-14）

| 约束 | 期望 | 实检 | 违反后果 |
| --- | --- | --- | --- |
| `setuptools<81` | `<81` | ✔（`mlx-audio` 依赖 `pkg_resources`） | 导入失败 |
| server 依赖 | `uvicorn[standard]`/`fastapi`/`python-multipart`/`webrtcvad` | ✔ 已装 | server 起不来 |
| Ollama `think` | **`false`** | ✔ | 流式 `content` **全空**（静默空结果） |
| 输入音频 | **16k PCM 单声道** | ✔ | 转写失败/错乱 |
| 流式收尾 | `flush()` | ✔ | 尾段丢失 |
| 服务绑定 | 回环/受信网络 | 见 §5 | 公网暴露风险 |

> 违反约束须**显式报错**，不得静默返回空结果（`RTM-CAP-14`）。

---

## 3. ObservationItem（观察项，CAP-13）

| 项 | 值 |
| --- | --- |
| 模型 | `mlx-community/NemotronLabs-VoiceChat-11B-4bit`（11.1 GB，openmdw-1.1） |
| 状态 | **观察项，`first_release=false`**——不得作首版主链路 |
| falsification_evidence | 加载 3.95–8.28 s；中文 33.36 s / 英文 16.29 s（输入 6.96/2.64 s，**4–6× 实时**）；**中英文输入返回同一段英文人格寒暄**（未体现对语音内容理解）；双工首个 assistant 文本内容跑偏；**未观测到 `function_delta`** |
| root_cause_candidates | MLX 移植接线 / 系统提示 / 语言设置 / 是否需 VAD 分段（均**未定位**） |
| exit_conditions | 出现可复现证据证明中文实时对话达标（理解内容 + 延迟可接受 + 工具体事件），或换对照样本（`kyutai/moshiko-mlx-q4` / `Qwen3-Omni-30B-A3B-AWQ-4bit`）后复评 |
| 保留要求 | **不得删除证据与复现脚本**（`voice-stack/scripts/03/06/07`） |

---

## 4. ServiceLevelBaseline（服务级基线，OBS-09）

| 项 | 值 |
| --- | --- |
| 场景 | `WS 流式 ASR → Ollama(qwen3.5 think=false) → HTTP TTS` |
| 环境 | Apple M5 Max / 128 GB / macOS 26.5.1；`mlx-audio` @ `127.0.0.1:8000` |
| 脚本 | `voice-stack/scripts/08_local_voice_loop.py`；日志 `logs/local_voice_loop.json` |
| 输入 | 6.96 s 中文语音 |
| 测量 | ASR 首字 1.23 s / 结束 7.14 s；LLM 首字 0.66 s；TTS 首字节 4.43 s；**端到端 12.23 s** |
| TTS 直跑 | 首包 3.34 s / RTF **0.66** / 24 kHz |
| ASR 准确度 | nemotron 流式 2 处错字（“语音链路”→“语音路”，“克隆”→“克龙”）；Qwen3-ASR 离线**逐字全对** |
| **口径** | **服务级（本机服务进程）** |
| 硬约束 | **不得作为 M1/M3 浏览器链路验收值；不得与浏览器样本混算 P95**（`RTM-OBS-09`、`RTM-EVD-06`） |

---

## 5. 暴露前提核实（SEC-08）

| 服务 | 监听 | 结论 |
| --- | --- | --- |
| `mlx-audio` server（PID 11803） | `127.0.0.1:8000` | ✔ 仅回环 |
| Ollama（PID 61441） | `*:11434`（IPv6 通配） | ⚠ **非仅回环**，可能被局域网访问；**待收紧**（绑定 `127.0.0.1`） |
| 浏览器直连 | 不直连本机服务 | ✔ 经 LFL 受信服务端回环转发 |

- `HF_TOKEN` 等凭据仅在服务端，不下发浏览器（`RTM-SEC-01/08`）。
- **待处理**：Ollama 绑定收敛至回环；许可逐项核实（nemotron/silero-vad / Tier B `IndexTTS-2.5`=`other`）。

---

## 6. 尚未冻结/待 M1 建立

| 项 | 状态 |
| --- | --- |
| 计时口径（客户端同一单调时钟） | 待 M1（`T-M1-3`） |
| 连接代次隔离 | 待 `T-CONTRACT-6` |
| 本地停播延迟基线 | **未建立**（浏览器侧 VAD→停播未测，`RTM-PRF-02`） |
| 双 ASR 终稿校正落地 | 待 `T-M1-11`（INP-09） |
| 工具调用编排落点 | 待 `T-CONTRACT-1/2`、`T-M2-3`（TOL-16） |

---

## 7. 阻断清单（v1.1 口径）

1. **浏览器链路接线未完成**：采集/16k 重采样/播放/VAD/打断未接入 LFL Web runtime → 探针 A/B **部分解除、不得宣布通过**。
2. **Ollama 监听通配接口**（`*:11434`）→ SEC-08 暴露前提待收紧。
3. **许可未逐项核实**：nemotron/silero-vad（许可未知）、Tier B `IndexTTS-2.5`（`other`）。
4. **VoiceChat 失败原因未定位**（观察项，非阻断首版）。

> **不允许**：以服务级已通或 mock 宣布 M0 完成（`RTM-EVD-03`、`RTM-CAP-07`）。

---

## 8. 对 M0 产物文档的更新建议（T-M0-4，不改 `docs/M0-…` 文件）

建议对 `docs/M0-REALTIME-MULTIMODAL-READINESS-20261023.md` 做以下定点更新（本轮仅建议，不直接改）：

1. §1 执行摘要：探针 A/B 由「阻断（无实时音频 Provider 凭据）」改为 **「部分解除：服务级已通、浏览器侧仍阻断」**；探针 C 保持通过并补注 TOL-16 编排落点。
2. §4 能力档案：由「各项未知」替换为**本档案的本地栈冻结表**（或改为引用本文件）。
3. §5 探针记录：补服务级已实测原始数据（12.23 s 等）并**标注口径=服务级**。
4. §7 阻断清单：替换为上文 §7 四项。
5. 新增：观察项条目（VoiceChat）、服务级基线条目（12.23 s）、SEC-08 暴露核实（Ollama 通配）。

---

## 9. 追溯

- RTM：CAP-01/02/04/05/07/11/12/13/14、SES-06、SEC-01/08、OBS-09、EVD-03/06、REC-02、AUD-01/03、INP-09、TOL-09/16、PLY-07。
- 防退化（`docs/DEVELOPMENT_REPAIR_SAFETY.md`）：能力事实为**实测**而非跨 runtime 搬运；性能数值**绑定环境与口径**；未把服务级结果冒充浏览器链路验收。