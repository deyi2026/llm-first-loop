---
title: MiniMax T2A v2 音频是 hex 编码而非 base64（附模型自然度选型表）
scenario: "用 MiniMax T2A v2 (https://api.minimax.chat/v1/t2a_v2) 做中文配音时，按 base64 解码 data.audio 会得到无法播放的垃圾字节。实测踩坑过程：先用 base64.b64decode 写文件，ffprobe 报 \"Invalid data found\"；实测确认 data.audio 是 hex 字符串（mp3 以 ID3 头 494433 开头，pcm 为裸 16bit 小端）。另外同一句台词在同一音色下比较 speech-02-hd / speech-2.6-hd / speech-2.8-hd，F0 语调起伏与动态范围差异显著，直接影响\"像不像真人\"的听感。"
root_cause: "MiniMax T2A v2 的 data.audio 字段编码格式与文档/直觉不符（hex 而非 base64）；TTS 音色\"真人感\"主要由模型版本与语调动态决定，而非音量或后期处理。"
solution: "1) 解码：若 len(a)%2==0 且前 256 字符全为 hex 字符，则用 binascii.unhexlify(a)；否则回退 base64.b64decode(a)。2) 模型选型（同一句\"小云啊……妈没事，就想听听你的声音。\"+ Chinese (Mandarin)_Warm_Girl + emotion=sad 实测）：speech-02-hd → F0 起伏 9.5 半音/变化率 σ=3.34/动态 23.1dB；speech-2.6-hd → 10.4/3.43/22.2；speech-2.8-hd → 13.5/5.27/29.4。2.8-hd 三项全面最优，是\"真人感\"的关键。3) 音色按角色分配：Chinese (Mandarin)_Mature_Woman（母亲）/ Sweet_Lady（女儿），情绪参数逐句映射。4) 语速务必做网格搜索：单向插值 want=base*(d/target) 会把 speed 顶到上限 1.60（明显机械）或下限 0.70（之后再叠 atempo=0.85 造成二次处理劣化）；改为在候选网格上挑\"时长误差最小且 speed 最接近 1.0\"的那个，atempo 只做 ±8% 微调。5) 尾部补静音前先做 8ms 淡出，硬接静音会产生咔哒声，本身就是机械感来源。"
evidence: 工具实测：04_tools/probe/fmt_probe2.py（hex vs base64 判别）、04_tools/probe/model_probe.py（6 个模型的 F0/动态对比）、04_tools/tts_v2.py（生成 13 句全绿）、04_tools/voice_naturalness.py（v1 vs v2 客观对比：F0 变化率 σ 2.68→4.36）。
tags: [minimax, tts, 配音, hex编码, 语音合成, 视频]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T20:42:25.213118+08:00"
updated_at: "2026-10-26T20:42:25.213118+08:00"
---