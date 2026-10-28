---
title: ffmpeg 多路混音链会让音轨被静默截断：amix=duration=first 与 sidechaincompress 的时长陷阱
scenario: "用 ffmpeg 复杂滤镜链合成含人声+音乐的成片（本地视频生成流水线的后期环节）：adelay 摆放多句配音 → amix(inputs=N,duration=longest) → loudnorm → sidechaincompress 压音乐 → amix(inputs=2,duration=first) → loudnorm → alimiter。结果成片音轨仅 4.49 秒而视频 60.5 秒，约 92.6% 无声；而 loudnorm 仍报 -16 LUFS，常规响度检查完全无法察觉。"
root_cause: ""
solution: "1) 根因定位：逐段渲染音频链测每级输出时长，定位到两处不可靠语义——(a) amix=duration=first 在该链上输出 2.03s（等于第一条配音的时长），而非预期的\"第一条输入时长\"；(b) sidechaincompress 输出被截到 54.6s（早于两侧输入）。2) 改法：放弃在 ffmpeg 内做多路混音，改为 numpy 预混——读取各配音 wav 按 in_point 累加进定长缓冲，按人声区间构造软侧链包络（Hann 窗卷积平滑），音乐按包络压低后与人声相加，产出单条与目标等长的 mix.wav；ffmpeg 图只保留 [amixin]→loudnorm(两遍)→alimiter。3) 验收必须补独立检查：解码整条音轨的采样点数换算秒数，与视频流时长比对，差值 >0.3s 即判失败；并用分窗 RMS 确认人声段与音乐段同时存在（人声/音乐床分离度 ≥6dB）。4) 流程上：这类\"静默截断\"只有独立审查子代理能可靠发现，交付前把\"音轨时长对齐\"列入验收清单。"
evidence: 复现与修复均在 $HOME/lfl-workspace/work/psa-video-1min：04_tools/diag_audio.py（V1=57.46s 正常、V2=57.46s、V4 全链=2.03s 截断）、diag_audio2.py（W2 amix=duration=first→2.03s；W3 duration=longest→54.78s；W4 去 sidechain→60.50s）、mix_audio.py（numpy 预混，voice/music 分离度 +8.0dB）、verify_audio.py（音视频时长差 0.001s）。修复前独立审查子代理实测音轨 4.488s / 视频 60.5s 判 FAIL；修复后音轨 60.501s、-16.1 LUFS、0 黑帧，独立审查复判 PASS。
tags: [ffmpeg, amix, sidechaincompress, loudnorm, 视频后期, 混音, 交付验收, 独立审查]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-26T19:41:23.706832+08:00"
updated_at: "2026-10-26T19:41:23.706832+08:00"
---

当前性验证：复现命令 `cd <项目>/04_tools && python3 diag_audio.py` 应显示 V1=57.46s 正常而 V4 全链≈2.03s 被截断；若你的 ffmpeg 版本行为不同，请重跑该脚本再据此决策，不要照搬结论。修复后的验收命令 `python3 verify_audio.py <成片.mp4>` 应输出 "audio-vs-video delta" 绝对值 < 0.3s。