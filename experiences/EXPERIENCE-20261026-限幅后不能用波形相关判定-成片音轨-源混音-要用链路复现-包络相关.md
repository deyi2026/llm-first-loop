---
title: "限幅后不能用波形相关判定\"成片音轨=源混音\"，要用链路复现+包络相关"
scenario: "成片链路含 alimiter(attack=5ms) 时，用\"成片音轨 vs 源混音的波形相关\"判断内容是否同一，得到接近 0 的值，差点误判为\"成片装错了素材\"。"
root_cause: "判据选错：把\"内容同一性\"判据压在逐样本波形相关上，而成片链路的限幅环节是快动作增益处理，天然改写波形形状，样本级相关不适用于该判据。正确判据是\"用同一条链路复现输入并与成片比特级比对\"+ 包络级相关。"
solution: "判定成片音轨的内容同一性时，不要用逐样本波形相关：成片链路末端的快动作限幅（alimiter attack=5ms/release=50）会逐样本改写波形形状，源混音与成片的波形相关会掉到 0 附近甚至变负。正确做法是\"链路复现\"：用与成片完全相同的 ffmpeg 音频链路单独处理源混音，再与成片音轨逐样本比对（同一输入同一链路 → AAC 编码确定性 → r=1.0000），并辅以包络级（50ms 帧 RMS）相关作为形状判据；同时必须跑负对照（另一个版本的混音）以证明判据有区分力。"
evidence: "work/psa-video-1min/04_tools/final_audio_identity.py 实测：final_v3.mp4 音轨 vs mix_v3.wav 原混音 波形r=-0.2502/包络r=0.9954；vs mix_v3 经成片同款链路重编码 波形r=1.0000；vs mix_v2 波形r=-0.1960。两个独立子代理复核均 VERDICT: PASS（其中一位把\"内容同一性未正面证明\"列为未闭合项，随后被上述链路复现闭合）。"
tags: [audio-verification, ffmpeg, loudnorm, alimiter, correlation, independent-review]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-26T21:21:30.815154+08:00"
updated_at: "2026-10-26T21:21:30.815154+08:00"
---