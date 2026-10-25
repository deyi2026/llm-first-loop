# MiniMax H3 本地视频接入与优化建议

## 接入边界

H3 Ref2VA 是视频/原生音频扩散模型。GGUF 只是权重格式，不能用现有
`llama-server /v1/chat/completions` 加载。本实现独立调用支持 H3 的
stable-diffusion.cpp；保留既有 lfrt、Qwen、MLX 和 StateBraid 聊天链路。

Web 模型管理页增加“MiniMax H3 · 本地视频”，视频模型选择项为 MiniMax H3。可保存四个模型组件路径、
CPU placement 和超时，输入描述/参考图生成视频，取消后台任务，播放并下载 MP4。
保存配置对新任务生效；运行中的任务使用已经冻结的配置。

此版本支持文字描述与最多 9 张静态参考图；视频/音频参考导入尚未提供。
输出必须包含实际的视频流和音频流，后端退出 0 但无文件/缺音轨不计成功。

## 安装与配置

需要支持 H3 的 `sd-cli`（启用 Metal 与 WebM）、`ffmpeg`、`ffprobe`，以及：

| 组件 | 文件 | 角色 |
|---|---|---|
| 已有 Ref2VA 权重 | `minimax_h3_ref2va_pruned-Q4_K.gguf` | 参考条件视频/音频扩散 |
| 编码器 | `qwen3vl_32b_minimax_h3-Q4_K_M.gguf` | H3 专用 Qwen3-VL，不能替换成普通聊天权重 |
| 视频 VAE | `vae/minimax_h3_video_vae_fp16.safetensors` | 视频解码 |
| 音频 VAE | `vae/minimax_h3_audio_vae_fp32.safetensors` | 原生音频解码 |

默认模型目录为 `~/.lmstudio/models`，上述路径默认在
`unsloth/MiniMax-H3-GGUF/` 内。可用 `LFL_VIDEO_MODEL_ROOT` 显式改变根目录。
Web 允许填写该根目录内的相对/绝对组件路径，拒绝目录逃逸和越界软链接。

由服务启动环境设置 `LFL_VIDEO_SD_CLI` 为已验证 `sd-cli` 的绝对路径；
也可通过服务 PATH 提供 `sd-cli`。现有 `.env` 加载入口经统一 Settings 解析这两个
配置项，再显式传给视频运行层；运行层不自行重读环境变量。后台 worker 和
guardian 绑定同一源码目录，不依赖外部 PYTHONPATH 指向的安装版本。
Web 不提供任意可执行文件或 shell 参数输入。

先在隔离环境验证，完成仓库规定的独立审查与原版完整 R9 后，才安排 main
集成及 Web 配置激活。修改源码或 `.env` 不代表运行中的 Web 已加载这些内容。

## LFL 工具调用

LFL 原生工具 `video_generation` 复用 Web 配置和同一执行槽：

- `action=status` 查询模型组件、配置与任务。
- `action=generate, model=minimax-h3, prompt=...` 异步提交，返回 `job_id`。
- `action=job, job_id=...` 查询终态，成功后返回 `output_url` 播放/下载链接。
- `action=cancel, job_id=...` 请求取消；不会自动重试。

H3 是视频模型，通过视频选择项与专用工具调用。部署保留当前聊天模型选择和聊天服务。
普通 diffusion Flash Attention 完整 8 步验收无提速且音频等价门槛未通过，
运行命令显式固定 `--flash-attn off,te=on`，不采用近似缓存或实验内核。

## 请求与生命周期

- H3 固定使用 `--mode vid_gen`、`--cfg-scale 1.0`、24 fps。
- 宽高显式要求 32 的倍数，帧数为 `17k+5`，避免后端悄悄扩展请求尺寸。
- 初始设置 640×384、56 帧、8 步；这些是待实机校准的起点，不宣称最佳配置。
- Web 提供一键低分辨率预览（256×256、22 帧、4 步），不改变已保存的模型
  配置。本机同权重/参考图的一次实测约 64 秒生成约 0.918 秒、有音轨的 MP4；
  这是单次观测，不是速度承诺。分辨率/时长/步数都可以继续调整。
- 参考图先保存原始字节与 SHA-256，再做 EXIF 方向修正和 PNG 转换；原图有
  独立鉴权读取入口。完整请求、配置、实际命令、日志和产物摘要均持久保存。
- 每个数据目录只有一个视频执行槽，跨 Web 重连/重启保持。不会自动重试生成。
- 独立 guardian 检测 worker 的 pipe EOF，负责取消、超时、终止和回收其后端
  进程组；worker 被 SIGKILL 的场景有真实受控子进程回归测试。
- 不宣称能抵抗所有监督进程被同时强制终止。guardian 自身被外部 SIGKILL
  的全面恢复尚未完成资格验证。
- 原生音视频先保留为 WebM，再转为适合浏览器播放的 H.264/AAC MP4。
  ffprobe 检验流组成和实际播放时长，成功产物绑定 SHA-256。
- 状态、配置、上传、任务和文件路由沿用既有 Web 鉴权/精确 Origin 防护。

主要 API 为 `/api/v1/video`、`/config`、`/references`、`/jobs`、
`/jobs/{id}/cancel`、`/jobs/{id}/files/{output|log|request}`，以及
`/references/{id}/source`。所有子路径以前缀 `/api/v1/video` 为基准。

## research 的复用判断

已读取 `runtime/README.md`、`runtime/lfrt` 的当前实现及只读运行状态，
并核对 `StateBraid/README.md` 与 `cognitive-cache/cognitive_cache.py`。

| 已有组件 | 对本次接入的处理 |
|---|---|
| lfrt | 继续管理现有 8901 聊天服务；复用 Web 现有管理入口，不将视频任务伪装成聊天模型切换 |
| StateBraid | 保留语言模型前缀/KV 连续性能力；当前支持矩阵未包含 H3 扩散后端 |
| cognitive-cache | 属于 MLX-LM prompt-cache 原型，不能直接作为 H3 去噪缓存 |
| 已有 llama.cpp/MLX forks | 保持当前职责；H3 使用独立、固定版本的视频 backend |

因此，“采用 research”不应变成把语言模型的缓存、token 预算或 sampler 默认值
复制到 H3。可复用运行事实、生命周期边界与已有 Web 管理入口；数值加速需在
H3 专用后端重新测量。

## 建议继续优化的顺序

1. **先测完整短片基线**：同一 prompt/seed/参考图，记录加载、文本编码、去噪、
   VAE、转码各段时长与内存峰值；同时检查输出有画面、有声音、时长与尺寸正确。
   文件大小和空闲内存采样不能替代峰值验收。
2. **按阶段放置和释放组件**：比较编码器 CPU 与 Metal、按需卸载以及 VAE
   tiling 的真实差异。Apple 统一内存下，CPU 卸载不等于降低总内存需求。
3. **校准去噪参数**：固定质量用例，分别比较步数、分辨率和时长；以质量、
   端到端耗时和峰值为依据，不能用聊天模型 tok/s 衡量视频吞吐。
4. **再考虑编码结果复用**：仅当重复文本编码成为实测瓶颈时，增加绑定全部
   模型组件指纹、prompt、参考原图和预处理参数的精确缓存；不做相似语义命中。
5. **最后决定与聊天模型的内存协调**：先观察共存峰值；需要腾出资源时复用
   lfrt 的活动观察/等待空闲机制，再明确选择停旧启新。现有机制不是严格 drain，
   本接入没有自动停止或重启聊天服务。

## 来源

- [Unsloth H3 GGUF 模型卡](https://huggingface.co/unsloth/MiniMax-H3-GGUF)
- [sd.cpp H3 运行说明](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/minimax_h3.md)
- [sd.cpp Metal 构建](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/build.md)
- [H3 VAE](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae)

实机准备使用 sd.cpp commit `0886f11b6b8b4d1f6259e0f1337cae554284c37a`；
Unsloth 组件固定 revision `babc040eff0084465460ead58fdb8ec44296f8dd`；
Comfy-Org VAE 固定 revision `e5eb578a89295337b8ff433a035929ce0279e0b6`。
下载组件需按各自 LFS SHA-256 校验完成，不能把 `.h3-partial` 视为可用权重。
