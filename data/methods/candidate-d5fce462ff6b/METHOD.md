---
method_id: candidate-d5fce462ff6b
name: 本地视频模型短片交付流水线（编剧→导演→生成→后期→独立审查）
description: 用本地 MiniMax H3 逐镜生成素材，配合编剧/导演/视频制作/后期四个子代理分工，最终产出带中文配音、原创配乐、字幕与结尾卡的 1 分钟真人出镜公益短片；含验收门槛与实测踩坑清单。
aliases: MiniMax H3 短片流水线, 本地视频生成到成片, 视频四子代理分工
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:611007c7-8311-4eb8-896f-2687efc09f46:0:75d09900aef240c19a7f
parent_ref: method-root-cause
created_at: 2026-10-26T19:41:25.333134+08:00
updated_at: 2026-10-26T19:41:25.333134+08:00
---
适用：需要在本机用 MiniMax H3（sd-cli / Q4 GGUF）产出带配音与音乐的真人出镜短片，且被要求"按子代理分工完成并交付成品"。

流程骨架（本次实测于 macOS M5 Max / 128G）：
1) 编剧子代理 → 只出题材与台词表（字数与语速对齐，≤4.5 字/秒）。
2) 导演子代理 → 出逐镜 H3 提示词 + 帧数/步数/seed + 人物锚点 + 参考图标签映射；镜头时长加总 = 成片时长。
3) 视频制作子代理 → 逐镜提交 H3 作业。硬约束：
   - 每个数据目录只有一个视频执行槽，作业排队串行；作业之间不要并发提交期望并行。
   - 参考图必须走"参考图入口"上传：本地 loopback 的 POST /api/v1/video/references（multipart 字段名 file）可免鉴权直连，返回参考图 ID；再用 references=[id] 提交作业。
   - 人物一致性：首镜出图后抽帧回灌做参考图，ref2va 路线可显著提升跨镜同一人。
   - 帧数必须是 17k+5（如 56/73/90/107/124/141），分辨率取 32 倍数（640x384）。
   - 实测成本：56 帧约 3-4 分钟；141 帧双参考约 26 分钟。15 镜全片约 4-5 小时。
4) 后期子代理（建议由主代理兜底执行）→ macOS `say -v Tingting` 逐句配音；numpy 合成配乐；字幕用 PIL 画卡；ffmpeg 合成。
5) 验收（关键）：音视频时长差 ≤0.3s；响度两遍 loudnorm 落 -16 LUFS；0 黑帧；YAVG 90-130；逐镜画音对齐（字幕窗口 = 该镜 start_sec+0.10）。

踩坑清单（均为本次实际踩到）：
- ffmpeg amix=duration=first 与 sidechaincompress 会静默截断音轨 → 改 numpy 预混，ffmpeg 只做 loudnorm/limiter。
- 单遍 loudnorm 不收敛（-11.5 LUFS）→ 两遍：第一遍把 print_format=json 放进 filter_complex 图内并把 -loglevel 提到 info 读 input_i/input_tp/input_lra/input_thresh，第二遍用 measured_* + linear=true。-af 不能与 filter_complex 混用。
- 素材清单顺序可能与分镜顺序不一致 → 合成时必须按 shots.json 的 start_sec 排序，不要信任清单顺序，并加缺失告警。
- 配音入点若用取整的预估值，会比真实切点早 0.1-0.8s（字幕落在上一镜尾部）→ 必须用真实 start_sec 重算。
- 结尾卡与最后一句字幕会重叠 → 结尾卡起点按"最后字幕终点 + 0.3s"设。
- 自合成配乐若泛音倍数写错会只剩基频（像风琴）→ 合成后必查波峰因数（应 ≥6dB）与频段能量。

交付纪律：成片在 present_files 之前必须由独立子代理对当前产物出 PASS（且 PASS 覆盖的文件指纹须与交付文件一致）；独立审查往往能抓到自己验收漏掉的阻断项（本例抓到音轨截断与画音错位）。
