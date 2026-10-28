---
title: 合成音频必须用客观统计验收：波峰因数/频段能量/人声音乐分离度 + ffmpeg 两遍 loudnorm 收敛法
scenario: "用 numpy 自行合成配乐与多路语音混音后，缺少客观判据：只按峰值归一就交付，结果音乐像风琴（泛音同相导致波形趋近方波）且盖过人声；而 ffmpeg 单遍 loudnorm 也未收敛到目标响度，单看\"已做归一化\"无法发现。"
root_cause: ""
solution: "交付前用客观统计代替主观听感：(1) dc_check.py 输出每轨 DC 偏移/峰值/RMS/波峰因数——音乐 crest 应 ≥6dB（<3dB 即同相谐波堆叠，听感刺耳）；(2) spec_music.py 做 FFT 频段能量占比，确认基频+泛音分布正常（避免泛音倍数写错导致只有基频的\"单薄\"音色）；(3) profile_mix.py 用\"台词窗口 RMS vs 间隙窗口 RMS\"量化人声/音乐分离度，要求 ≥6dB；(4) 响度用两遍 loudnorm：第一遍把 print_format=json 放在 filter_complex 图内并把 -loglevel 提到 info 读取 input_i/input_tp/input_lra/input_thresh，第二遍用这些 measured_* + linear=true 精确落到目标 LUFS。"
evidence: 实证见 $HOME/lfl-workspace/work/psa-video-1min：04_tools/dc_check.py（首版音乐 crest=1.6dB、100-1k 能量 49.9% 判为同相谐波堆叠）、04_tools/spec_music.py（修正后 crest=9.6dB、含真实 2/3 次泛音）、04_tools/make_music.py（修正 m 倍频系数后能量分布正常）、04_tools/profile_mix.py（修正配比后 separation=+8.0dB）。两遍 loudnorm 实测：单遍时 Integrated=-11.5 LUFS 未收敛，两遍（measured_* + linear=true）后 -16.0 LUFS / -4.3 dBTP。
tags: [音频合成, numpy, loudnorm, 两遍归一, 客观验收, 配乐, 人声可懂度]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T19:22:36.903635+08:00"
updated_at: "2026-10-26T19:22:36.903635+08:00"
---

当前性验证：跑 `python3 04_tools/dc_check.py` 与 `python3 04_tools/spec_music.py`（本机路径）应分别打印 wave/peak/rms/crest 与频段能量占比；若 crest < 3dB 说明信号趋近方波/饱和，需重制；跑 `python3 04_tools/profile_mix.py` 应输出 voice/music separation ≥ 6dB。