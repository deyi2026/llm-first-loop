---
title: "合成配乐变\"嗡鸣/恐怖\"的根因是持续 pad，配乐必须以音符事件为主"
scenario: "为公益短片做背景音乐床时，用 numpy 自研合成（持续 pad + 稀疏动机 + 低频 pulse）铺满全片，用户反馈\"是个嗡鸣声，听起来很恐怖，并不是音乐\"。"
root_cause: "配乐由\"持续 pad + 稀疏拨弦动机 + 低频 pulse\"构成：pad 铺 14 秒一个和弦、能量集中在 150-800Hz（band_ratio -1dB，远高于其他频段）、detune 失谐造成拍频、低频 pulse(92/138Hz) 提供\"嗡\"的体感；音符事件密度过低（60s 仅 18 次动机）使听感成为 drone。悬疑/惊悚配乐正是这种写法，因此用户感知为\"恐怖\"。"
solution: |
  配乐重心必须是"音符事件序列"而非持续铺底：(1) 固定 BPM 的小节网格与和弦进行；(2) 有乐句的旋律（句末留休止，乐句呼吸是"像音乐"的关键）；(3) 伴奏音色全部是会衰减的（拨弦/软钢琴/钢片琴），全曲零持续音；(4) 副歌段加打击乐给拍点；(5) 低频只保留短促拨弦，砍掉 150Hz 以下持续成分。验收用三项客观指标：主导音持续时长中位数、音高变化次数/分、旋律音高命中率 + 节拍周期检出。
  当前性验证（在本仓库可复现）：cd work/psa-video-1min && python3 04_tools/music_diag.py 04_audio/music_v2.wav 应得 median_sustain_s≈6.87、pitch_changes_per_min≈6.0；python3 04_tools/music_diag.py 04_audio/music_v3.wav 应得 median_sustain_s≈0.49、pitch_changes_per_min≈71.4；python3 04_tools/music_verify.py 04_audio/music_v3.wav 04_audio/music_v3_events.json 应得 melody_hit_rate_octave_tolerant≈0.93、bpm_estimate≈95。
evidence: "work/psa-video-1min/04_tools/music_v2.py (pad/motif/pulse)；music_diag.py 实测 music_v2.wav: median_sustain_s=6.87, max_sustain_s=26.25, pitch_changes_per_min=6.0；v3 music_v3.wav 实测 median_sustain_s=0.49, pitch_changes_per_min=71.4, 旋律命中率 92.9%, 检出 95.3BPM, 6/6 乐句有呼吸；用户原话\"背景音乐是个嗡鸣声，听起来很恐怖\""
tags: [bgm, audio, music-synthesis, drone, psa-video]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-26T21:12:04.874206+08:00"
updated_at: "2026-10-26T21:12:04.874206+08:00"
---